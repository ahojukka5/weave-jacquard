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
- deterministic canonical `.weave` rendering and node source maps.

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

Install a `weavec` package containing the public `weavec build` command, or point
the server to a development compiler binary:

```bash
export WEAVE_DB_PATH="$PWD/weave.db"
export WEAVE_BUILD_ROOT="$PWD/.weave-build"
export WEAVEC_SOURCE_ROOT="../weavec"
export WEAVEC_BIN="../weavec/build/weavec"
```

`WEAVEC_BIN` is optional when `weavec` is already available on `PATH`.
`WEAVEC_SOURCE_ROOT` is used only by grammar discovery to scan the compiler's
surface fixture corpus. `WEAVE_BUILD_ROOT` controls where immutable build
artifacts are stored; the default is `.weave-build` beside the database.

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

A typical stdio client configuration is:

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
→ program_create
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

`program_build` resolves the selected branch to one immutable revision before it
does any rendering or compiler work:

```text
branch head
    ↓ pin
immutable revision
    ↓
canonical program.weave + program.weave.map.json
    ↓
weavec build program.weave -o program
    ↓
native executable + manifests + diagnostics
```

The compiler owns surface lowering, WIR, LLVM IR, object generation, private
runtime selection, and target linking. `weave_frontend` invokes only the public
source-to-executable command. It never selects a runtime archive or invokes
`clang` itself.

A build returns a content-derived build ID and artifact paths. Successful builds
with the same revision content, document, compiler hash, and target are reused.
A failed build records diagnostics but does not mutate the database revision or
publish an executable.

The artifact store contains:

```text
.weave-build/<build-id>/
├── program.weave
├── program.weave.map.json
├── compiler-manifest.json
├── diagnostics.json
├── manifest.json
└── program
```

`manifest.json` records the project, branch, pinned revision and root hash,
source hash, compiler path and hash, target, invoked public command, return code,
and hashes of all produced artifacts.

The same operation is available outside MCP:

```bash
weave-build --db weave.db build demo main.weave --branch main
weave-build --db weave.db get <build-id>
```

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

Those wrappers are transport metadata, not Weave syntax. The compiler receives:

```lisp
(fn main
  (params)
  (returns i32)
  (do (return (const_i32 42))))
```

Canonical source and `weave-node-map-v1` are generated in one deterministic
render operation. The map records UTF-8 byte offsets and line/column spans for
every node, together with the source hash and revision. Future machine-readable
compiler diagnostics can therefore be mapped to the smallest containing node
without teaching `weavec` about database IDs.

## Grammar discovery and validation

`grammar_help` searches:

```text
$WEAVEC_SOURCE_ROOT/test/correctness/surface
```

It reports observed forms, parent forms, arities, examples, and fixture paths.
This is construction guidance rather than a duplicate normative grammar.

The completed-program language check remains:

```text
program_validate → weavec --frontend output.wir input.weave
```

Native production uses:

```text
program_build → weavec build input.weave -o program
```

## Parallel agents and merge

Each agent should work on a database branch:

```text
branch_create(project="demo", branch="agent/foo")
branch_create(project="demo", branch="agent/bar")
```

Merge uses stable node identities and a three-way tree comparison. Independent
changes are retained; incompatible edits are reported as conflicts. A merged
state must still pass structural and compiler validation.

## MCP tools

The current server exposes:

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

See [`docs/mcp.md`](docs/mcp.md), [`docs/compiler-bridge.md`](docs/compiler-bridge.md),
and [`docs/architecture.md`](docs/architecture.md).

## Development

```bash
python -m compileall -q src tests
ruff check .
pytest --cov=weave_frontend --cov-report=term-missing
```

Repository invariants and contribution rules are documented in
[`AGENTS.md`](AGENTS.md) and [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Current limitations

- grammar help is derived from examples rather than a formal registry;
- exact node-mapped compiler diagnostics wait for `weavec`'s machine-readable
  source-span output; current build diagnostics retain stdout, stderr, and status;
- published compiler packages currently determine which native target is
  available;
- build execution is local and compilation is separate from future sandboxed
  `program_run`;
- immutable database snapshots are intentionally simple rather than compact;
- merge is conservative;
- the MCP and typed AST prototypes still coexist.

## License

Apache-2.0. See [`LICENSE`](LICENSE).
