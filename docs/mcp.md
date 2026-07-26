# weave-mcp

## Purpose

`weave-mcp` is Jacquard's primary agent interface. It lets coding agents
construct, inspect, validate, merge, and build Weave programs without replacing
complete source files or balancing large S-expressions in one call.

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

Jacquard does not invoke LLVM tools, choose runtime archives, or link programs
itself.

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
- `branch_history`: compact first-parent history read retained for compatibility.
- `branch_history_page`: read bounded first-parent pages with an explicit
  continuation and ordered operation metadata.
- `revision_operations_page`: inspect exact immutable operation targets and JSON
  payloads for one revision in sequence-number pages.
- `branch_activity_summary`: measure complete first-parent revision, operation,
  merge, author, and edit-grouping activity.
- `branch_merge`: perform stable-ID three-way merge.

Incompatible edits produce a conflict and do not advance the target branch.

`branch_history_page` accepts page sizes from 1 to 200. Begin without a start
revision; when `has_more` is true, pass `next_revision_id` as the next
`start_revision_id`. A continuation must be reachable from the selected branch
head. Compare `branch_head_revision_id` between pages when a stable multi-page
read is required.

`revision_operations_page` is project-scoped and accepts sequence-number pages
of 1 to 200 rows. When `has_more` is true, pass `next_sequence_number` as the
next `start_sequence_number`. Revisions and operation rows are immutable, so no
branch-head stability check is needed while paging one revision. Each row
preserves its stored ID, kind, target, and parsed JSON payload.

`branch_activity_summary` reports descriptive workflow metrics, including
single- and multi-operation revisions and the number of revisions avoided by
operation grouping. These metrics should guide ergonomics work, not encourage
agents to maximize batch size. See
[`branch-activity.md`](branch-activity.md) for exact definitions.

## Program documents

### `program_create`

Create a `(program ...)` document with name and version forms.

### `program_import`

Import a complete source document. This is intended for migration and tests;
agents should prefer structural writes for normal work.

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
→ structural source edits
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

## Structural writes

### Single-node tools

- `node_create_form(parent_id, head, position)`
- `node_add_atom(parent_id, kind, value, position)`
- `node_set_atom(node_id, value)`
- `node_move(node_id, new_parent_id, position)`
- `node_wrap(node_id, head)`
- `node_delete(node_id)`

Use these while exploring unfamiliar code, repairing one uncertain location, or
when an inspection is useful after every decision. Each successful single-node
write creates one immutable revision.

### `node_apply_batch`

Use a batch after one coherent local structure is known. It accepts 1–256 flat,
ordered operations using the same six operation kinds listed above. It never
accepts a nested replacement tree.

A created form, atom, or wrapper may set `as="alias"`; later operations in the
same batch refer to it as `@alias`. The response maps surviving aliases to stable
node IDs for use in later calls.

`expected_revision_id` provides optimistic concurrency. A stale branch head is
rejected before publication. All operations are applied in memory, the complete
tree is validated once, and one SQLite transaction writes:

- one immutable revision and snapshot;
- one ordered audit row per sub-operation;
- one compare-and-set branch-head update.

Any invalid operation, alias, reference, position, final tree, or stale-head
check rejects the complete batch. No partial revision or audit rows remain.

The default response reports aggregate counts and aliases. Set
`include_operation_results=true` only when the caller needs compact results for
every sub-operation. See [`edit-transactions.md`](edit-transactions.md) for the
full request and operation contract.

Atom kinds are `symbol`, `string`, `integer`, `float`, and `boolean`. Positions
are zero-based and default to append.

## Inspection and shared context

- `node_inspect`: return a bounded annotated subtree and grammar hint.
- `node_find`: find stable IDs by form head, atom kind, or exact value.
- `context_add`: store project-, document-, or symbol-scoped design material.
- `context_get`: retrieve context visible at the current branch revision.

Reading may return a useful local subtree. Writing remains transactional: one
single edit or one bounded coherent batch either publishes completely or not at
all.

## Failure and publication semantics

- Rejected single edits and batches do not advance branches.
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
