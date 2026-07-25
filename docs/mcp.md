# weave-mcp

## Purpose

`weave-mcp` is the primary agent interface to `weave_frontend`. It lets coding
agents construct, inspect, validate, merge, and build Weave programs without
replacing complete source files or balancing large S-expressions in one call.

The database owns node identity, immutable revisions, branches, context, and
build provenance. `weavec` remains the authoritative language frontend and
native compiler.

## Compiler authority

Grammar help is derived from the configured compiler checkout. It is
construction guidance, not a duplicate language specification.

Authoritative validation is:

```text
canonical ordered source set
→ weavec --frontend output.wir source0.weave source1.weave ...
```

Authoritative native compilation is:

```text
canonical ordered source set
→ weavec build source0.weave source1.weave ... -o program
```

`weave_frontend` does not invoke LLVM tools, choose runtime archives, or link
programs itself.

## Stable node identities

Every list and atom has an ID such as `n_3a12cce48fe14f99`.

- changing an atom preserves its ID;
- moving a node preserves its ID;
- new nodes receive new IDs;
- branches retain IDs inherited from their base revision;
- structural merge compares IDs rather than line numbers.

`program_render(annotated=true)` and `node_inspect` can expose these IDs.
Compiler sources never include the annotations. Each built source receives a
separate `weave-node-map-v1` sidecar.

## Projects and branches

### `project_initialize`

Create a project, its initial revision, and the `main` branch.

### `branch_create`

Create a branch from another branch head.

### `branch_list`

List branches and their current immutable revision IDs.

### `branch_history`

Follow a branch's first-parent revision history.

### `branch_merge`

Run a stable-ID three-way merge. Independent changes are retained;
incompatible edits produce a conflict and do not advance the target branch.

## Program documents

### `program_create`

Create a `(program ...)` document with name and version forms.

### `program_import`

Import one complete source document. This is intended for migration and test
fixtures; agents should prefer atomic writes for normal work.

### `program_list`

List all database documents, including reserved structural metadata.

### `program_source_list`

List only compiler source documents. Revisioned build-target metadata is
excluded.

### `program_render`

Render canonical compiler source or an annotated agent view.

### `program_validate`

Validate one document from the current branch head through `weavec --frontend`.
For multi-document programs, use a named target and `build_target_validate`.

### `program_build`

Build an explicit ordered document set from one pinned revision.

Inputs:

```text
project
 document                         primary source
 additional_documents            optional ordered sources
 branch = "main"
 revision_id = optional exact revision
 target = optional compiler target triple
```

The primary document is always first. Additional documents retain the supplied
order. Duplicates are rejected and the server never silently includes all
project documents.

## Revisioned named targets

A named target stores the compiler input order and target triple in the same
immutable revision graph as its source documents.

### `build_target_set`

Create or update a target definition.

```text
build_target_set(
  project="demo",
  name="application",
  document="main.weave",
  additional_documents=["library.weave", "platform.weave"],
  compiler_target="native"
)
```

### `build_target_list`

List targets from a branch head or exact revision.

### `build_target_get`

Read one target definition from a branch head or exact revision.

### `build_target_delete`

Delete a target in a new immutable revision.

### `build_target_validate`

Resolve the target definition and all ordered source documents from one pinned
revision, render canonical sources, and invoke `weavec --frontend`.

### `build_target_build`

Build the exact same revisioned target through the native compiler bridge.

Recommended multi-document flow:

```text
build_target_set
→ atomic source edits
→ build_target_validate
→ branch_merge
→ build_target_build
→ build_get
```

## Build inspection

### `build_get`

Read a stored frontend build manifest and absolute artifact paths by build ID.
The compiler does not need to remain installed for inspection.

A successful build contains canonical sources, node maps, compiler manifest,
raw compiler diagnostics, mapped bridge diagnostics, frontend manifest, and
the executable.

Cache-integrity and concurrent-publication hardening is tracked in issue #17.

## Atomic writes

- `node_create_form(parent_id, head, position)`
- `node_add_atom(parent_id, kind, value, position)`
- `node_set_atom(node_id, value)`
- `node_move(node_id, new_parent_id, position)`
- `node_wrap(node_id, head)`
- `node_delete(node_id)`

Atom kinds are `symbol`, `string`, `integer`, `float`, and `boolean`. Positions
are zero-based and default to append.

Each successful write creates one immutable revision. A rejected write does not
advance the branch.

## Inspection

### `node_inspect`

Return a bounded annotated subtree, parent information, position, and grammar
hint.

### `node_find`

Find stable IDs by form head, atom kind, or exact value.

Reading may return a useful local subtree. Writing remains atomic.

## Shared context

### `context_add`

Store project-, document-, or symbol-scoped design material in revision
history.

### `context_get`

Retrieve context visible at the current branch revision.

This lets parallel agents share interface contracts and decisions without
relying on an unversioned prompt.

## Failure semantics

- Validation and build failures do not mutate program revisions.
- Builds never advance branches.
- Missing or duplicate selected documents fail before compilation.
- A final executable exists only after compiler and diagnostics-protocol success.
- Diagnostics preserve compiler stdout, stderr, timeout state, and return code.
- Source spans map only through the exact canonical source named by the compiler.
- Spanless, ambiguous, and non-canonical locations remain unmapped.
- Program execution is intentionally separate from compilation and is not yet a
  general MCP operation.

## Configuration

| Variable | Purpose |
|---|---|
| `WEAVE_DB_PATH` | SQLite program database |
| `WEAVE_BUILD_ROOT` | Immutable build artifact root |
| `WEAVEC_BIN` | Compiler used for validation and builds |
| `WEAVEC_SOURCE_ROOT` | Compiler checkout used by grammar help |
