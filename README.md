# Jacquard

**Jacquard is the agent-native programming environment for Weave.** Coding
agents edit a versioned S-expression tree through structural MCP operations
instead of repeatedly replacing complete source files.

The name refers to the Jacquard loom: a programmable mechanism that turns a
stored pattern into coordinated weaving operations. Here, agents modify the
program pattern, Jacquard preserves its structure and history, and `weavec`
turns the canonical result into a native executable.

Repository and Python distribution: **`weave-jacquard`**  
Public Python namespace: **`weave_jacquard`**  
Primary executables: **`weave-mcp`** and **`weave-build`**

## Responsibilities

Jacquard owns:

- single-node and bounded transactional edits with stable node identities;
- immutable revisions, parallel branches, structural merge, and measured branch activity;
- project-, document-, and symbol-scoped context;
- compiler-corpus-backed grammar help;
- authoritative validation through `weavec --frontend`;
- revisioned named build targets and ordered multi-document builds;
- deterministic canonical sources and per-document node maps;
- compiler diagnostics mapped back to database nodes and exposed in bounded pages;
- verified, content-derived native build artifacts.

Jacquard is not another compiler. The user-facing
[`weavec`](https://github.com/ahojukka5/weavec) compiler owns the Weave language,
surface lowering, WIR, LLVM generation, runtime selection, object generation,
and linking.

## Architecture

The supported workspace is `SExpressionWorkspace`. It inherits a small internal
grammar-neutral revision service responsible only for:

- SQLite lifecycle;
- projects, branches, checkout, and history;
- immutable state load and commit;
- common-ancestor discovery;
- merge orchestration through workspace-specific hooks.

Language structure is not duplicated in Python; `weavec` remains authoritative.
The current implementation package remains internal, while new public imports
use `weave_jacquard`.

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
`WEAVEC_SOURCE_ROOT` is required only for compiler-corpus-backed grammar help.

Native builds require `weavec >= 0.3.0`, or another compiler implementing:

- `weavec build`;
- `weavec-build-manifest-v1`;
- `weavec-diagnostics-v1`.

Run the stdio MCP server:

```bash
weave-mcp
```

## Recommended agent workflows

Single-document program:

```text
project_initialize
→ program_create / program_import
→ grammar_help
→ single-node edits while exploring
→ node_apply_batch for a coherent known structure
→ node_inspect
→ program_validate
→ branch_merge
→ branch_activity_summary when measuring the workflow
→ program_build
→ build_get
→ build_diagnostics_page when the build failed
→ node_inspect(revision_id = failed revision) before repair
```

Multi-document program:

```text
program_source_list
→ build_target_set
→ structural source edits
→ build_target_validate
→ branch_merge
→ build_target_build
→ build_get
→ build_diagnostics_page when the build failed
→ node_inspect(revision_id = failed revision) before repair
```

A target definition and every selected source are resolved from one immutable
revision. The primary document is first and additional documents retain their
stored order.

`node_apply_batch` accepts a flat list of up to 256 existing structural
operations. Temporary `@aliases` refer to nodes created earlier in the same
request. The complete batch publishes as one revision or rolls back; existing
single-node tools remain available for uncertain edits and repairs.

For long branches, `branch_history_page` returns bounded first-parent pages with
an explicit continuation. `revision_operations_page` returns exact immutable
operation targets and payloads for one revision in sequence-number pages.
`branch_activity_summary` reports complete revision, operation, merge, author,
and edit-grouping metrics without changing history.

For failed builds, `build_diagnostics_page` returns exact mapped diagnostics in
bounded pages after verifying the immutable build and the bytes being read. An
agent can follow a returned stable `node_id` without opening files on the MCP
server machine. Passing the returned build `revision_id` to `node_inspect`
reproduces the exact failing subtree even after the branch has advanced. Without
`revision_id`, the same tool continues to inspect the current branch head.

## Compiler boundary

Validation invokes only the public compiler frontend:

```text
weavec --frontend output.wir source0.weave source1.weave ...
```

Native builds invoke only the public build command:

```text
weavec build source0.weave source1.weave ... -o program \
  --manifest-json compiler-manifest.json \
  --diagnostics-json compiler-diagnostics.json
```

Jacquard never invokes LLVM tools, a linker, or a runtime archive directly.

## Stable node identities

Every list and atom has a stable ID such as `n_3a12cce48fe14f99`. Editing or
moving an existing node preserves its ID. Branches inherit IDs from their base
revision, and merge compares stable identities rather than line numbers.

Agent rendering may expose transport wrappers:

```lisp
(@n_function
  (fn main
    (@n_params (params))
    (@n_returns (returns i32))
    (@n_body (do (return (const_i32 42))))))
```

Those wrappers are not Weave syntax. Compiler sources are canonical unannotated
text. A separate `weave-node-map-v1` records node IDs and UTF-8 source spans.

## Builds and integrity

A successful build contains:

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

The bridge validates both compiler protocol documents before retaining an
executable. `build_get` and cache admission verify the frontend manifest, build
ID, path containment, regular-file status, and every SHA-256 hash.
`build_diagnostics_page` performs the same verified admission and hashes the
exact diagnostic bytes it decodes before returning mapped entries.

`weave-build-key-v4` derives the build ID from the immutable revision, ordered
source hashes, compiler binary hash, and requested target. Concurrent builds use
a per-build advisory lock. An existing verified successful build wins; failed
or incomplete candidates cannot erase it.

The historical protocol identifier `weave-frontend-build-manifest-v2` remains
unchanged for stored-build compatibility. It names a data format, not the
current product.

## Revision storage

Each successful single-node write creates one immutable revision. A bounded
transaction records every ordered sub-operation while publishing one immutable
revision for the complete batch. Snapshot JSON uses an adaptive, versioned BLOB
representation:

- `WJZ1` for zlib-compressed canonical JSON;
- `WJR1` when raw canonical JSON is smaller.

Legacy databases migrate transactionally. Databases with a newer schema version
are rejected without modification.

## CLI

```bash
weave-build --db weave.db target-set demo application main.weave \
  --source library.weave
weave-build --db weave.db target-validate demo application
weave-build --db weave.db target-build demo application
weave-build --db weave.db get <build-id>
```

Failures are emitted as structured JSON on stderr with exit status 2.

## MCP tools

- **Help:** `weave_help`, `grammar_help`
- **Projects and branches:** `project_initialize`, `branch_create`,
  `branch_list`, `branch_history`, `branch_history_page`,
  `revision_operations_page`, `branch_activity_summary`, `branch_merge`
- **Programs:** `program_create`, `program_import`, `program_list`,
  `program_source_list`, `program_render`, `program_validate`, `program_build`
- **Named targets:** `build_target_set`, `build_target_list`,
  `build_target_get`, `build_target_delete`, `build_target_validate`,
  `build_target_build`
- **Build inspection:** `build_get`, `build_diagnostics_page`
- **Single-node editing:** `node_create_form`, `node_add_atom`, `node_set_atom`,
  `node_move`, `node_wrap`, `node_delete`
- **Transactional editing:** `node_apply_batch`
- **Inspection:** `node_inspect`, `node_find`
- **Context:** `context_add`, `context_get`

## Further documentation

- [Architecture](docs/architecture.md)
- [MCP tool reference](docs/mcp.md)
- [Transactional structural edits](docs/edit-transactions.md)
- [Branch activity observability](docs/branch-activity.md)
- [Build diagnostic inspection](docs/build-diagnostics.md)
- [Revision-pinned node inspection](docs/revision-node-inspection.md)
- [Compiler bridge](docs/compiler-bridge.md)
- [Revisioned build targets](docs/build-targets.md)
- [Target validation](docs/target-validation.md)
- [Snapshot storage](docs/snapshot-storage.md)
