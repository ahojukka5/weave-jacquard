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

`program_render(annotated=true)` and `node_inspect` expose these IDs. Compiler
sources never include annotations. Each materialized source receives a separate
`weave-node-map-v1` sidecar.

## Projects and branches

- `project_initialize`: create a project, initial revision, and `main` branch.
- `branch_create`: create a branch from another branch head.
- `branch_list`: list branches and immutable head revisions.
- `branch_history`: follow first-parent history.
- `branch_merge`: perform stable-ID three-way merge.

Incompatible edits produce a conflict and do not advance the target branch.

## Program documents

### `program_create`

Create a `(program ...)` document with name and version forms.

### `program_import`

Import a complete source document. This is intended for migration and tests;
agents should prefer atomic writes for normal work.

### `program_list`

List all database documents, including reserved structural metadata.

### `program_source_list`

List only compiler source documents from a branch head or exact revision.
Revisioned build-target metadata is excluded.

### `program_render`

Render canonical compiler source or an annotated agent view.

### `program_validate`

Validate one document through `weavec --frontend`. For a multi-document program,
use a named target and `build_target_validate`.

### `program_build`

Build an explicit ordered document set from one pinned revision.

```text
project
 document                         primary source
 additional_documents            optional ordered sources
 branch = "main"
 revision_id = optional exact revision
 target = optional compiler target triple
```

The primary document is first. Additional documents retain supplied order.
Duplicates are rejected and no command silently includes all project documents.

## Revisioned named targets

A named target stores compiler input order and a target triple in the same
immutable revision graph as its source documents.

- `build_target_set`: create or update a target definition.
- `build_target_list`: list targets at a branch head or exact revision.
- `build_target_get`: read one target definition.
- `build_target_delete`: delete a target in a new revision.
- `build_target_validate`: validate target metadata and ordered sources from one
  pinned revision.
- `build_target_build`: compile the exact same revisioned target.

Recommended flow:

```text
program_source_list
→ build_target_set
→ atomic source edits
→ build_target_validate
→ branch_merge
→ build_target_build
→ build_get
```

## Build inspection

### `build_get`

Read a stored frontend build manifest and absolute artifact paths by build ID.
The compiler does not need to remain installed.

Before returning data, `build_get` verifies:

- the frontend manifest format and its 32-character lowercase build ID;
- that the manifest build ID matches its directory;
- that every artifact reference is relative and remains below the build root;
- that artifact references and hash keys match exactly;
- that every referenced artifact is a regular file;
- that every SHA-256 hash is lowercase and matches the current file contents.

A successful cache hit additionally requires build-key v4, return code zero,
both compiler protocol documents to be valid, and all required source, node-map,
diagnostics, manifest, and executable artifacts to be present.

The raw `weavec-build-manifest-v1` is validated against the requested target,
ordered materialized sources, requested output, and compiler status. Invalid or
missing compiler provenance produces `bridge.invalid-compiler-manifest` and
withholds the executable.

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

## Inspection and shared context

- `node_inspect`: return a bounded annotated subtree and grammar hint.
- `node_find`: find stable IDs by form head, atom kind, or exact value.
- `context_add`: store project-, document-, or symbol-scoped design material.
- `context_get`: retrieve context visible at the current branch revision.

Reading may return a useful local subtree. Writing remains atomic.

## Failure and publication semantics

- Validation and build failures do not mutate program revisions.
- Builds never advance branches.
- Missing or duplicate sources fail before compilation.
- A final executable exists only after compiler process, compiler manifest, and
  compiler diagnostics success.
- Raw malformed compiler evidence is retained for investigation.
- Source spans map only through the exact canonical source named by the compiler.
- Spanless, ambiguous, and non-canonical locations remain unmapped.
- Build work occurs in a temporary sibling directory.
- Publication uses a per-build advisory lock and atomic rename.
- An existing verified successful build wins over concurrent failed, incomplete,
  or later successful candidates.
- Temporary and quarantined candidate directories are cleaned.
- Program execution remains separate from compilation.

## Configuration

| Variable | Purpose |
|---|---|
| `WEAVE_DB_PATH` | SQLite program database |
| `WEAVE_BUILD_ROOT` | Immutable verified build artifact root |
| `WEAVEC_BIN` | Compiler used for validation and builds |
| `WEAVEC_SOURCE_ROOT` | Compiler checkout used by grammar help |
