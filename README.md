# weave_frontend

`weave_frontend` is an experimental **agent-native programming environment**
for Weave. Coding agents edit a versioned S-expression tree through small MCP
tool calls instead of repeatedly generating and replacing complete source files.

The primary executable is **`weave-mcp`**. It provides:

- atomic form and atom edits;
- stable semantic node IDs;
- immutable revision history;
- parallel branches and structural merge;
- grammar help derived from the canonical compiler corpus;
- authoritative validation through `weavec --frontend`;
- revision-pinned native builds through `weavec build`;
- ordered multi-document compiler inputs;
- deterministic canonical `.weave` rendering and per-document node maps;
- compiler diagnostics mapped back to stable database nodes.

> The model decides what program to build. The environment owns tree structure,
> identity, history, build provenance, and transactional safety. `weavec` owns
> the language and native toolchain.

## Status

This repository is a runnable prototype, not a replacement compiler. The
user-facing compiler is [`weavec`](https://github.com/ahojukka5/weavec). This
project uses that compiler as the language authority and source-to-executable
build service while experimenting with a more reliable editing interface for
coding agents.

The repository contains two related prototypes:

1. **`weave-mcp`** — the primary grammar-neutral MCP server for atomic
   S-expression construction and native builds.
2. **Typed AST prototype** — the earlier frontend used to prove immutable
   revisions, validation, context, and semantic merge.

## Installation

Python 3.11 or newer is required.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

Install a `weavec` build that supports both `--manifest-json` and
`--diagnostics-json`, or point the server to a development compiler binary:

```bash
export WEAVE_DB_PATH="$PWD/weave.db"
export WEAVE_BUILD_ROOT="$PWD/.weave-build"
export WEAVEC_SOURCE_ROOT="../weavec"
export WEAVEC_BIN="../weavec/build/weavec"
```

`WEAVEC_BIN` is optional when `weavec` is already on `PATH`.
`WEAVEC_SOURCE_ROOT` is used only by grammar discovery to scan compiler
fixtures. `WEAVE_BUILD_ROOT` controls immutable build artifacts; the default is
`.weave-build` beside the database.

Run the stdio MCP server:

```bash
weave-mcp
```

### Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `WEAVE_DB_PATH` | SQLite program database | `weave.db` |
| `WEAVE_BUILD_ROOT` | Revision build artifact store | `.weave-build` beside DB |
| `WEAVEC_SOURCE_ROOT` | `weavec` checkout used by grammar help | unset |
| `WEAVEC_BIN` | compiler used for validation and native builds | `weavec` from `PATH` |

Tree editing and stored-build inspection work independently of compiler source.
Grammar examples require the source checkout. Validation and new native builds
require the compiler binary.

## MCP client configuration

```json
{
  "mcpServers": {
    "weave": {
      "command": "/path/to/venv/bin/weave-mcp",
      "env": {
        "WEAVE_DB_PATH": "/path/to/project/weave.db",
        "WEAVE_BUILD_ROOT": "/path/to/project/.weave-build",
        "WEAVEC_SOURCE_ROOT": "/path/to/weavec",
        "WEAVEC_BIN": "/path/to/weavec/build/weavec"
      }
    }
  }
}
```

The exact outer format depends on the MCP client. The command and environment
variables are the relevant contract.

## Recommended agent workflow

```text
weave_help
→ project_initialize
→ program_create / program_import
→ grammar_help
→ node_create_form / node_add_atom
→ node_inspect
→ program_validate
→ branch_merge
→ program_build
→ build_get
```

Agents should call `grammar_help` before using an unfamiliar form and should
prefer atomic writes over bulk `program_import`.

## Database revision to executable

`program_build` resolves a branch to one immutable revision before rendering:

```text
branch head
    ↓ pin once
immutable revision
    ↓
ordered canonical sources + one node map per source
    ↓
weavec build source0.weave source1.weave ... -o program
    ↓
native executable + manifests + mapped diagnostics
```

The primary `document` is always first. Optional `additional_documents` are
passed after it in exactly the order supplied:

```text
program_build(
  project="demo",
  document="main.weave",
  additional_documents=["library.weave", "platform.weave"],
  branch="main"
)
```

The bridge does not silently include all project documents and does not sort the
list. Duplicate names are rejected. Every selected document is read from the
same pinned revision, and source order is part of the content-derived build ID.

The compiler owns surface lowering, WIR, LLVM IR, object generation, private
runtime selection, and target linking. `weave_frontend` invokes only the public
source-to-executable command. It never selects a runtime archive or invokes
`clang` itself.

The same operation is available outside MCP:

```bash
weave-build --db weave.db build demo main.weave \
  --source library.weave \
  --source platform.weave

weave-build --db weave.db get <build-id>
```

Each repeated `--source` preserves command-line order.

## Build artifacts

A multi-document build uses deterministic indexed filenames so duplicate
basenames cannot collide:

```text
.weave-build/<build-id>/
├── sources/
│   ├── 000-main.weave
│   ├── 001-library.weave
│   └── 002-platform.weave
├── source-maps/
│   ├── 000-main.weave.map.json
│   ├── 001-library.weave.map.json
│   └── 002-platform.weave.map.json
├── compiler-manifest.json
├── compiler-diagnostics.json
├── diagnostics.json
├── manifest.json
└── program
```

`weave-frontend-build-manifest-v2` records the ordered database document names,
canonical source hashes, relative source/map paths, compiler hash, target,
command, diagnostics validity, return code, and all artifact hashes.

For existing single-document consumers, `artifacts.source` and
`artifacts.node_map` remain aliases for the primary document. New consumers can
use `artifacts.sources` and `artifacts.node_maps` for the complete ordered set.

Successful builds with the same revision content, ordered document set,
compiler hash, and target are reused through `weave-build-key-v3`. Failed or
incomplete builds are never cache hits.

## Agent view and compiler view

Every list and atom has an internal stable ID such as `n_...`. Agent-facing
rendering may expose wrappers:

```lisp
(@n_function
  (fn main
    (@n_params (params))
    (@n_returns (returns i32))
    (@n_body (do (return (const_i32 42))))))
```

Those wrappers are transport metadata, not Weave syntax. Each compiler source is
rendered without wrappers. Canonical source and `weave-node-map-v1` are produced
in one deterministic operation for each selected database document.

## Mapped diagnostics

`compiler-diagnostics.json` is the raw `weavec-diagnostics-v1` document.
`diagnostics.json` is the validated `weave-build-diagnostics-v1` view.

For a canonical source span, the bridge:

1. identifies the exact materialized source named by the compiler;
2. selects that source's node map;
3. chooses the smallest containing stable node;
4. adds the original database `document` and `node_id`.

A secondary-file diagnostic therefore maps to the secondary document rather
than the primary one. Spanless, ambiguous, generated-WIR, and non-canonical
locations remain unmapped instead of being guessed. Invalid compiler protocol
output is retained for investigation but prevents executable publication.

## Grammar discovery and validation

`grammar_help` searches:

```text
$WEAVEC_SOURCE_ROOT/test/correctness/surface
```

It reports observed forms, parent forms, arities, examples, and fixture paths.
This is construction guidance rather than a duplicate normative grammar.
Completed-program validation remains:

```text
program_validate → weavec --frontend output.wir input.weave
```

Native production uses:

```text
program_build → weavec build <ordered sources> -o program
```

## Parallel agents and merge

Each agent should work on a database branch. Merge uses stable node identities
and a three-way tree comparison. Independent changes are retained; incompatible
edits are reported as conflicts. A merged state must still pass structural and
compiler validation.

## MCP tools

- **Help:** `weave_help`, `grammar_help`
- **Projects and branches:** `project_initialize`, `branch_create`,
  `branch_list`, `branch_history`, `branch_merge`
- **Programs:** `program_create`, `program_import`, `program_list`,
  `program_render`, `program_validate`, `program_build`
- **Builds:** `build_get`
- **Atomic editing:** `node_create_form`, `node_add_atom`, `node_set_atom`,
  `node_move`, `node_wrap`, `node_delete`
- **Inspection:** `node_inspect`, `node_find`
- **Context:** `context_add`, `context_get`

See [`docs/mcp.md`](docs/mcp.md),
[`docs/compiler-bridge.md`](docs/compiler-bridge.md), and
[`docs/architecture.md`](docs/architecture.md).

## Development

```bash
python -m compileall -q src tests
ruff check .
pytest --cov=weave_frontend --cov-report=term-missing
```

When GitHub Actions capacity is unavailable, run these commands and focused
compiler-bridge integration harnesses locally before merging.

## Current limitations

- grammar help is derived from examples rather than a formal registry;
- exact surface syntax spans are available, while some backend locations still
  depend on conservative unique-token inference until locations propagate
  explicitly through WIR;
- callers repeat ordered document lists because persistent named build targets
  are not implemented yet;
- published compiler packages determine which native target is available;
- build execution is local and compilation is separate from future sandboxed
  `program_run`;
- immutable database snapshots are intentionally simple rather than compact;
- merge is conservative;
- the MCP and typed AST prototypes still coexist.

## License

Apache-2.0. See [`LICENSE`](LICENSE).
