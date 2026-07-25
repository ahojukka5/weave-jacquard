# weave_frontend

`weave_frontend` is the agent-facing programming environment for Weave.
Coding agents edit a versioned S-expression tree through small MCP operations
instead of repeatedly replacing complete source files.

The primary executable is **`weave-mcp`**. It provides:

- atomic form and atom edits;
- stable node identities;
- immutable revisions and parallel branches;
- structural three-way merge;
- project-, document-, and symbol-scoped context;
- compiler-corpus-backed grammar help;
- authoritative validation through `weavec --frontend`;
- revisioned named build targets;
- ordered multi-document native builds through `weavec build`;
- deterministic canonical sources and node maps;
- compiler diagnostics mapped back to database nodes;
- content-derived build artifacts and cache provenance.

`weave_frontend` is **not another compiler frontend**. It owns editing,
identity, history, source materialization, and build provenance. The
user-facing [`weavec`](https://github.com/ahojukka5/weavec) compiler owns the
language, surface lowering, WIR, LLVM generation, runtime selection, object
generation, and linking.

## Status

The grammar-neutral S-expression workspace and `weave-mcp` are the supported
product direction.

The repository still contains an earlier typed-AST prototype and the legacy
`weave-front` command. They are not part of the intended production path and
are scheduled for removal after their shared revision mechanics are extracted;
see issue #14.

## Installation

Python 3.11 or newer is required.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

Configure the workspace and compiler:

```bash
export WEAVE_DB_PATH="$PWD/weave.db"
export WEAVE_BUILD_ROOT="$PWD/.weave-build"
export WEAVEC_BIN="../weavec/build/weavec"
export WEAVEC_SOURCE_ROOT="../weavec"
```

`WEAVEC_BIN` is optional when `weavec` is on `PATH`.
`WEAVEC_SOURCE_ROOT` is needed only for corpus-backed grammar help.

`program_build` and `build_target_build` require **`weavec >= 0.3.0`**. Earlier
compiler releases do not provide the public `weavec build`,
`weavec-build-manifest-v1`, and `weavec-diagnostics-v1` contracts used by the
native build bridge. Validation-only operations that invoke `weavec --frontend`
remain separate from this native-build requirement.

Run the stdio MCP server:

```bash
weave-mcp
```

### Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `WEAVE_DB_PATH` | SQLite program database | `weave.db` |
| `WEAVE_BUILD_ROOT` | Immutable build artifact store | `.weave-build` beside the database |
| `WEAVEC_BIN` | Compiler used for validation and builds | `weavec` from `PATH` |
| `WEAVEC_SOURCE_ROOT` | Compiler checkout used by grammar help | unset |

Tree editing, history, merge, and stored-build inspection work without a
compiler checkout. Validation and new builds require the compiler binary.

## Recommended agent workflow

For a single-document program:

```text
project_initialize
→ program_create / program_import
→ grammar_help
→ atomic node edits
→ node_inspect
→ program_validate
→ branch_merge
→ program_build
→ build_get
```

For a multi-document program, define the compiler input set once as a named
target:

```text
build_target_set
→ build_target_validate
→ build_target_build
→ build_get
```

A target definition and all of its source documents are resolved from one
immutable revision. The primary document is first; additional documents retain
the stored order.

## MCP client configuration

```json
{
  "mcpServers": {
    "weave": {
      "command": "/path/to/venv/bin/weave-mcp",
      "env": {
        "WEAVE_DB_PATH": "/path/to/project/weave.db",
        "WEAVE_BUILD_ROOT": "/path/to/project/.weave-build",
        "WEAVEC_BIN": "/path/to/weavec/build/weavec",
        "WEAVEC_SOURCE_ROOT": "/path/to/weavec"
      }
    }
  }
}
```

The outer configuration format depends on the MCP client. The executable and
environment variables are the relevant contract.

## Compiler boundary

Validation materializes canonical sources and invokes only the public compiler
frontend:

```text
immutable revision
    ↓
ordered canonical .weave sources
    ↓
weavec --frontend output.wir source0.weave source1.weave ...
```

A native build follows the same source order:

```text
immutable revision + compiler hash + target
    ↓
weavec build source0.weave source1.weave ... -o program
    ↓
executable + compiler manifest + diagnostics
```

The bridge never invokes LLVM or `clang` directly and never selects a runtime
archive.

## Named targets and CLI

Create and validate a revisioned build target:

```bash
weave-build --db weave.db target-set demo application main.weave \
  --source library.weave \
  --source platform.weave

weave-build --db weave.db target-validate demo application
weave-build --db weave.db target-build demo application
```

Use an exact historical revision without moving a branch:

```bash
weave-build --db weave.db target-validate demo application \
  --branch main \
  --revision <revision-id>
```

An ad hoc ordered build remains available:

```bash
weave-build --db weave.db build demo main.weave \
  --source library.weave \
  --source platform.weave

weave-build --db weave.db get <build-id>
```

Each repeated `--source` preserves command-line order. Duplicate documents are
rejected, and no command silently includes every project document.

## Stable IDs and compiler source

Every list and atom receives a stable ID such as `n_3a12cce48fe14f99`.
Editing or moving an existing node preserves its ID. Branches inherit IDs from
their base revision, and merge compares stable identities rather than line
numbers.

Agent rendering may expose ID wrappers:

```lisp
(@n_function
  (fn main
    (@n_params (params))
    (@n_returns (returns i32))
    (@n_body (do (return (const_i32 42))))))
```

Those wrappers are transport metadata, not Weave syntax. Compiler input is
canonical `.weave` text without annotations. A separate `weave-node-map-v1`
records UTF-8 byte and line/column spans for every node.

## Builds and diagnostics

A successful multi-document build contains:

```text
.weave-build/<build-id>/
├── sources/
├── source-maps/
├── compiler-manifest.json
├── compiler-diagnostics.json
├── diagnostics.json
├── manifest.json
└── program
```

`weave-frontend-build-manifest-v2` records the pinned revision, ordered source
documents, source hashes, compiler hash, target, command, return code, artifact
paths, and artifact hashes.

`compiler-diagnostics.json` is the raw `weavec-diagnostics-v1` document.
`diagnostics.json` is the validated and node-mapped
`weave-build-diagnostics-v1` view. A diagnostic is mapped only when its source
and span unambiguously match one canonical source map; otherwise it remains
unmapped rather than being guessed.

Build IDs are derived from revision content, ordered source hashes, compiler
hash, and target. Failed or incomplete builds are not cache hits. Additional
cache-integrity and concurrent-publication hardening is tracked in issue #17.

## Revision storage

Each mutation creates an immutable revision. Snapshot JSON is stored in an
adaptive versioned BLOB representation:

- `WJZ1` for zlib-compressed canonical JSON;
- `WJR1` when raw canonical JSON is smaller.

Legacy databases migrate transactionally on first open and are vacuumed once
after migration. Keep a consistent backup and avoid concurrent writers during
that first migration startup. See [snapshot storage](docs/snapshot-storage.md).

## MCP tools

- **Help:** `weave_help`, `grammar_help`
- **Projects and branches:** `project_initialize`, `branch_create`,
  `branch_list`, `branch_history`, `branch_merge`
- **Programs:** `program_create`, `program_import`, `program_list`,
  `program_source_list`, `program_render`, `program_validate`, `program_build`
- **Named targets:** `build_target_set`, `build_target_list`,
  `build_target_get`, `build_target_delete`, `build_target_validate`,
  `build_target_build`
- **Build inspection:** `build_get`
- **Atomic editing:** `node_create_form`, `node_add_atom`, `node_set_atom`,
  `node_move`, `node_wrap`, `node_delete`
- **Inspection:** `node_inspect`, `node_find`
- **Context:** `context_add`, `context_get`

## Further documentation

- [Architecture](docs/architecture.md)
- [Revisioned build targets](docs/build-targets.md)
- [Target validation](docs/target-validation.md)
- [Snapshot storage](docs/snapshot-storage.md)
- [MCP tool reference](docs/mcp.md)
