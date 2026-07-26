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
- structural merge compares IDs rather than line numbers;
- revision diffs compare immutable states through the same IDs.

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
- `branch_merge_preview`: preview stable-ID merge conflicts and consequences.
- `branch_merge_impact`: map prospective source changes to named build targets.
- `branch_merge_validate`: validate a named target from the exact merge candidate.
- `branch_merge`: publish a merge, optionally enforcing preview and compiler gates.

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

### `branch_merge_preview`

Preview the current source branch head into the current target branch head
without mutating either branch.

```text
project
target_branch
source_branch
```

The response format is `weave-merge-preview-v1`. Its deterministic `preview_id`
binds the project, branch direction, common ancestor, target head, and source
head.

A clean preview returns:

- `mergeable: true`;
- base, target-head, and source-head revision IDs;
- target, source, and prospective merged root hashes;
- changed document names;
- compact per-document node-change summaries.

A conflict preview is still a successful read response. It returns
`mergeable: false`, exact conflict paths, and no merged root. It does not advance
the target branch.

Per-document summaries report add/remove/modify status, document hashes, node
counts, changed stable-node count, and aggregate revision-diff change kinds.
Complete merged trees are never returned.

### `branch_merge_impact`

Map the changes introduced by merging the current source head into the current
target head to revisioned named build targets.

```text
project
target_branch
source_branch
preview_id = optional reviewed preview
start_index = 0
limit = 50
```

A supplied stale preview returns `STALE_MERGE_PREVIEW`. A semantic merge conflict
returns `MERGE_CONFLICT` before target analysis. The call is read-only and starts
no compiler process.

The response format is `weave-merge-target-impact-v1`. It reports:

- preview, ancestor, both head revisions, and prospective merged root;
- changed program documents;
- changed `@build-target/*` metadata documents;
- changed program documents covered by targets surviving in the candidate;
- changed program documents with no surviving target coverage;
- target counts before and after the merge;
- affected and unaffected candidate-target counts;
- a bounded page of affected target entries.

A target is affected when its definition is added, removed, or modified, or when
one of its primary/additional source documents changes. Each entry contains a
status, deterministic reasons, changed source documents, and compact before/after
target configurations.

The analysis is directional. It compares the current target state with the
prospective merged state and therefore reports only consequences introduced by
merging the source into that target. Changes already present on the target branch
are not reclassified as source merge impact.

Candidate coverage is calculated from targets that exist after the merge. A
removed target cannot hide a changed source from `uncovered_changed_documents`.
An uncovered document is not automatically invalid, but no named target can
validate it automatically.

Affected targets are sorted by name. `start_index` must be non-negative and
`limit` must be 1–200. When `has_more` is true, pass `next_index` as the next
`start_index`. The preview binds immutable revisions, so page order is stable.
See [`merge-impact.md`](merge-impact.md).

### `branch_merge_validate`

Validate one named target from the exact clean in-memory merge candidate without
publishing a revision or build artifact.

```text
project
target_branch
source_branch
build_target
preview_id = optional reviewed preview
```

The target definition and its ordered source documents are resolved from the
prospective merged state. Jacquard renders those canonical sources and invokes:

```text
weavec --frontend program.wir source0.weave source1.weave ...
```

A supplied stale preview returns `STALE_MERGE_PREVIEW`. A merge conflict returns
`MERGE_CONFLICT` before compiler startup. The response format
`weave-merge-validation-v1` includes:

- preview, ancestor, target-head, source-head, and merged-root identities;
- target configuration and ordered document names;
- stable source-root IDs, source hashes, and source byte counts;
- compiler path and binary SHA-256;
- availability, validity, return code, timeout state, and optional diagnostic;
- stdout and stderr bounded to 8,192 characters with truncation flags;
- WIR SHA-256 and byte count, but not WIR contents.

The deterministic `validation_id` binds the preview, merged root, target
configuration, ordered source hashes, and compiler hash. Validation creates no
revision and retains no temporary source or WIR files. See
[`merge-validation.md`](merge-validation.md).

### `branch_merge`

```text
project
target_branch
source_branch
preview_id = optional
validation_target = optional named build target
author = "merge-agent"
```

When `validation_target` is present, Jacquard recomputes the current candidate,
validates that named target through `weavec --frontend`, and rejects unavailable
or failed validation with `MERGE_VALIDATION_UNAVAILABLE` or
`MERGE_VALIDATION_FAILED`. The validation's exact preview ID becomes the
publication token.

When `preview_id` is supplied, a token mismatch returns
`STALE_MERGE_PREVIEW`; a matching conflict preview returns `MERGE_CONFLICT`.
Neither publishes a revision.

For a matching clean candidate, both reviewed branch heads are checked again in
the same SQLite `BEGIN IMMEDIATE` transaction that writes the merge revision.
The target update uses compare-and-set semantics. The merge revision records the
reviewed common ancestor and both parent heads in its operation payload.

A branch change before validation changes the preview ID. A branch change during
or after validation fails the transactional head check. The candidate that
passes the compiler is therefore the only candidate that can be published by the
validated call.

Calls without `preview_id` or `validation_target` remain supported. Direct merges
still capture and atomically recheck both current heads. Impact-aware
preview-validation-publication is recommended for independent agent work. See
[`merge-preview.md`](merge-preview.md), [`merge-impact.md`](merge-impact.md), and
[`merge-validation.md`](merge-validation.md).

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
- `branch_merge_impact`: identify candidate targets affected by a source merge.
- `branch_merge_validate`: validate a target from an uncommitted merge candidate.
- `build_target_build`: compile the exact same revisioned target.

Recommended flow:

```text
program_source_list
→ build_target_set
→ structural source edits
→ build_target_validate
→ branch_merge_preview
→ branch_merge_impact
→ review uncovered changed documents
→ branch_merge_validate(build_target = each affected surviving target)
→ branch_merge(preview_id = reviewed preview,
               validation_target = named target)
→ build_target_build
→ build_get
→ build_diagnostics_page when the build failed
→ node_inspect(revision_id = failed revision) before repair
→ revision_diff_page(base_revision_id = failed revision) against current head
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

### `build_diagnostics_page`

Read mapped retained diagnostic entries by build ID without opening files on the
server machine.

```text
build_id
start_index = 0
limit = 50
```

`start_index` must be a non-negative integer and `limit` must be between 1 and
200. The build first passes the same manifest, path-containment, regular-file,
and SHA-256 verification used by `build_get`. The retained
`weave-build-diagnostics-v1` document is then validated before entries are
returned.

The response includes compact build and compiler summaries, the total diagnostic
count, page fields, and exact mapped entries. When `has_more` is true, pass
`next_index` as the next `start_index`. Builds are immutable, so no branch-head
stability check is needed while paging.

Raw compiler stdout, stderr, malformed protocol documents, and protocol-error
details remain in the verified build artifacts and are not copied into the
bounded MCP response. See [`build-diagnostics.md`](build-diagnostics.md) for the
complete contract and repair workflow.

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

### `node_inspect`

Read a bounded annotated subtree and grammar hint by stable node ID.

```text
project
branch
document
node_id
depth = 3
revision_id = optional exact immutable revision
```

When `revision_id` is omitted, the tool reads the current branch head, preserving
its original behavior. When supplied, the revision must belong to `project`, but
it does not need to remain the selected branch head or be first-parent reachable
from it.

The response reports both `revision_id`, which identifies the state actually
inspected, and `branch_head_revision_id`, which identifies the current selected
branch head. `revision_is_branch_head` states whether they are equal. The node,
parent, position, subtree, rendering, and grammar hint all come from the exact
inspected revision.

This is the preferred way to inspect a mapped diagnostic after a branch has
advanced: pass the failed build's `revision_id` and the diagnostic `node_id`.
See [`revision-node-inspection.md`](revision-node-inspection.md).

### `revision_diff_page`

Compare one document across two immutable project revisions through stable node
IDs, without rendering and transferring two complete programs.

```text
project
document
base_revision_id
branch = "main"
target_revision_id = optional; defaults to branch head
start_index = 0
limit = 50
```

The explicit revisions must belong to `project`. They need not be related by
ancestry or reachable from the selected branch. The branch identifies the current
head and supplies the target when `target_revision_id` is omitted.

Each changed node contains compact `before` and `after` descriptors with its
kind, form head or atom value, parent, sibling position, and child count. Change
kinds are:

- `added` and `removed`;
- `kind_changed`, `head_changed`, and `value_changed`;
- `parent_changed` and `position_changed`;
- `child_count_changed`.

One stable ID produces one row, which may carry several change kinds. Common and
added nodes follow target preorder; removed nodes follow afterward in base
preorder. A document present on only one side produces an all-added or
all-removed diff. A document absent from both sides is rejected.

`start_index` must be non-negative and `limit` must be 1–200. The response
includes exact revision identities, whether the target is the branch head,
document-presence and node-count metadata, total and per-kind change counts, and
an explicit continuation. When `has_more` is true, pass `next_index` as the next
`start_index`. Both selected revisions are immutable, so the page order is
stable.

Use `node_inspect` with the relevant revision to expand any changed node into a
bounded local subtree. See [`revision-diff.md`](revision-diff.md) for the complete
contract and compiler-guided repair flow.

Other inspection and context tools:

- `node_find`: find stable IDs by form head, atom kind, or exact value.
- `build_diagnostics_page`: return bounded mapped diagnostics for a verified
  immutable build.
- `context_add`: store project-, document-, or symbol-scoped design material.
- `context_get`: retrieve context visible at the current branch revision.

Reading may return a useful local subtree, bounded change page, merge preview,
merge-impact page, or merge-validation record. Writing remains transactional:
one single edit, one coherent batch, or one merge either publishes completely or
not at all.

## Failure and publication semantics

- Rejected single edits and batches do not advance branches.
- Validation and build failures do not mutate program revisions.
- Builds never advance branches.
- Merge previews, merge impact analysis, merge candidate validation, historical
  inspection, and revision diffs never check out or rewrite revisions.
- Conflict previews and stale preview tokens publish no merge revision.
- Unavailable or failed merge validation publishes no merge revision.
- Merge publication atomically rechecks both captured branch heads.
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
