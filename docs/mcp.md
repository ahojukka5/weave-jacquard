# weave-mcp

## Purpose

`weave-mcp` is Jacquard's primary agent interface. Agents construct, inspect,
validate, review, merge, and build Weave programs through stable-ID structural
operations instead of replacing complete source files.

The database owns node identity, immutable revisions, branches, revisioned
context and merge policy, and build provenance. `weavec` remains the
authoritative language frontend and native compiler.

## Compiler authority

Grammar help is construction guidance derived from the configured compiler
checkout. It is not a duplicate language specification.

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

`program_render(annotated=true)` and `node_inspect` expose IDs. Compiler sources
never contain annotations. Materialized sources receive separate
`weave-node-map-v1` sidecars.

## Recommended protected-branch workflow

A project may publish a strict target-branch policy once:

```text
merge_policy_set(
  project,
  branch = "main",
  require_preflight = true,
  require_affected_validation = true,
  allow_uncovered_documents = false,
  max_affected_targets = project-appropriate bound)
```

Independent work then follows:

```text
branch_merge_preflight(project, target_branch, source_branch)
→ review target_merge_policy and source_merge_policy
→ review directional impact and uncovered documents
→ review complete affected-target validation_set
→ when ready_for_publication is true:
     call publication_tool with publication_arguments
```

Publication recomputes policy-aware preflight, compares `preflight_id`, enforces
the complete validation set, and atomically rechecks both branch heads before
writing the immutable merge revision.

## Projects, branches, and policy

Core tools:

- `project_initialize`: create a project, initial revision, and `main` branch.
- `branch_create`: create a branch from another branch head.
- `branch_list`: list branches and immutable head revisions.
- `branch_history`: compact compatibility history read.
- `branch_history_page`: bounded first-parent history with continuation.
- `revision_operations_page`: exact immutable operation audit pages.
- `branch_activity_summary`: complete first-parent workflow metrics.
- `merge_policy_get`: read effective first-parent policy.
- `merge_policy_set`: publish a policy in a new immutable revision.
- `branch_merge_preflight`: one-call non-mutating admission review.
- `branch_merge_preview`: low-level structural preview.
- `branch_merge_impact`: low-level directional target impact.
- `branch_merge_validate`: low-level one-target validation.
- `branch_merge_validate_affected`: complete affected-target validation set.
- `branch_merge`: policy-aware publication.

### `merge_policy_set`

```text
project
a branch = "main"
require_preflight = true
require_affected_validation = true
allow_uncovered_documents = false
max_affected_targets = 64
author = "policy-agent"
```

The actual argument is `branch`; the `a` prefixes above are not syntax and are
omitted in calls:

```text
merge_policy_set(
  project,
  branch = "main",
  require_preflight = true,
  require_affected_validation = true,
  allow_uncovered_documents = false,
  max_affected_targets = 64,
  author = "policy-agent")
```

The format is `weave-merge-policy-v1`. A successful call:

- validates policy values;
- stores or reuses an immutable project-scoped context document;
- records a `set_merge_policy` operation;
- publishes one new revision directly on the selected branch;
- returns policy, document, revision, and deterministic hash metadata.

`require_preflight=true` requires `require_affected_validation=true`.
`max_affected_targets` must be 1–64.

### `merge_policy_get`

```text
project
branch = "main"
revision_id = optional exact project revision
```

The registry walks first-parent history from the selected revision and returns
the newest policy operation. Historical reads reproduce the effective policy at
that revision.

When no policy was configured, the returned compatibility policy is:

```text
configured = false
require_preflight = false
require_affected_validation = false
allow_uncovered_documents = true
max_affected_targets = 64
```

It is resolved but not stored, preserving existing merge behavior.

### Target-branch authority

The current target branch's first-parent policy governs publication. The source
policy is returned for transparency. When hashes differ,
`source_policy_ignored=true`.

A source branch cannot weaken target admission by setting a permissive policy.
To loosen a protected branch, publish `merge_policy_set` directly on that target.
The new policy revision advances its head and invalidates older preview and
preflight evidence.

See [`merge-policy.md`](merge-policy.md).

## Merge preflight

### `branch_merge_preflight`

```text
project
target_branch
source_branch
preview_id = optional reviewed preview
allow_uncovered_documents = false
```

The format is `weave-merge-preflight-v1`. Preflight is read-only and composes:

1. target-authoritative and source-visible policy resolution;
2. stable-ID three-way preview;
3. directional named-target impact;
4. candidate coverage analysis;
5. validation of every affected target surviving in the candidate.

It returns:

- exact ancestor, target-head, source-head, preview, and merged-root identities;
- `target_merge_policy` and `source_merge_policy`;
- `source_policy_ignored`;
- a bounded impact summary;
- the complete `weave-merge-validation-set-v1`;
- `ready_for_publication`;
- `publication_tool = "branch_merge"`;
- exact `publication_arguments`, including policy-bound `preflight_id`.

The public impact summary contains at most 200 target entries. Truncation is
reported explicitly and affects presentation only; complete internal impact
still drives validation.

A forbidden uncovered override returns `MERGE_POLICY_VIOLATION` before impact or
compiler work. A policy fanout violation returns `TOO_MANY_AFFECTED_TARGETS`
before compiler startup.

`preflight_id` binds policy hashes and source-policy disposition in addition to
candidate, impact, validation-set, and uncovered-policy identities.

Preflight creates no revision, branch update, audit row, build manifest,
executable, retained source, or WIR artifact. See
[`merge-preflight.md`](merge-preflight.md).

## Lower-level merge review tools

### `branch_merge_preview`

```text
project
target_branch
source_branch
```

The `weave-merge-preview-v1` `preview_id` binds project, merge direction, common
ancestor, target head, and source head. A clean preview returns prospective root
and compact per-document stable-node consequences. A conflict preview returns
`mergeable=false` and exact conflict paths. Neither mutates a branch.

### `branch_merge_impact`

```text
project
target_branch
source_branch
preview_id = optional
start_index = 0
limit = 50
```

The `weave-merge-target-impact-v1` response reports only consequences introduced
by merging the source into the current target:

- changed program and target-metadata documents;
- candidate-covered and uncovered changed documents;
- target counts before and after;
- affected and unaffected target counts;
- paged affected-target entries with reasons and before/after definitions.

Coverage uses only targets surviving in the candidate. A removed target cannot
hide a changed source. Entries are sorted by target name; page sizes are 1–200.
See [`merge-impact.md`](merge-impact.md).

### `branch_merge_validate`

```text
project
target_branch
source_branch
build_target
preview_id = optional
```

Validates one target from the exact clean in-memory candidate through
`weavec --frontend`. `weave-merge-validation-v1` includes ordered source hashes,
compiler identity, bounded output, diagnostic status, and WIR hash/size. It
creates no revision or retained artifact. See
[`merge-validation.md`](merge-validation.md).

### `branch_merge_validate_affected`

```text
project
target_branch
source_branch
preview_id = optional
allow_uncovered_documents = false
```

The `weave-merge-validation-set-v1` response:

- validates every affected target surviving in the candidate;
- skips and reports removed targets;
- uses deterministic target-name order;
- aggregates all passes, rejections, and unavailable compilers;
- performs zero compiler work when uncovered documents block coverage;
- records the effective validation ceiling in result and identity.

The public tool uses the global bound of 64. Policy-aware preflight and
publication may impose a smaller target-branch ceiling. See
[`merge-validation-set.md`](merge-validation-set.md).

## Policy-aware publication

### `branch_merge`

```text
project
target_branch
source_branch
preview_id = optional
validation_target = optional named target
validate_affected_targets = false
allow_uncovered_documents = false
preflight_id = optional policy-aware preflight identity
author = "merge-agent"
```

Modes remain compatible when target policy permits them:

- direct structural merge;
- one explicit `validation_target`;
- complete `validate_affected_targets=true`;
- exact policy-aware preflight replay.

A call cannot combine single-target and all-target validation. A preflight replay
requires all-target validation and no `validation_target`.

Configured target policy may require preflight and all-target validation, forbid
uncovered overrides, or impose a lower validation ceiling. Policy failures occur
before publication:

- `MERGE_POLICY_PREFLIGHT_REQUIRED`;
- `MERGE_POLICY_AFFECTED_VALIDATION_REQUIRED`;
- `MERGE_POLICY_VIOLATION`;
- `STALE_MERGE_PREFLIGHT`;
- `TOO_MANY_AFFECTED_TARGETS`.

For `preflight_id`, Jacquard recomputes policy-aware preflight once, compares the
exact identity, enforces its validation set, and publishes with its preview ID.
It does not launch a redundant second compiler fanout for the same candidate.

Both target and source heads are then rechecked in the same SQLite
`BEGIN IMMEDIATE` transaction that writes the two-parent merge revision. A branch
or policy change before replay changes preflight identity; a change after
validation fails the transactional head check.

The result records:

- `merge_policy_enforced`;
- target and source policies;
- `source_policy_ignored`;
- `preflight_enforced` and `preflight_id`;
- individual or complete validation evidence;
- reviewed preview/parent metadata.

Every error leaves target branch and audit tables unchanged.

## History and audit

`branch_history_page` accepts limits 1–200. Begin without `start_revision_id`; use
`next_revision_id` for continuation. A continuation must remain reachable from
the selected branch head.

`revision_operations_page` accepts sequence-number pages of 1–200 rows. Immutable
operation records preserve ID, kind, target, and parsed payload. Policy revisions
appear as `set_merge_policy` operations.

`branch_activity_summary` reports descriptive revision, operation, merge, author,
and grouping metrics. Do not maximize batch size only to reduce counts.

## Program documents

- `program_create`: create a basic `(program ...)` document.
- `program_import`: import complete source for migration and tests.
- `program_list`: list all structural documents.
- `program_source_list`: list compiler sources, excluding reserved target metadata.
- `program_render`: render canonical or annotated source.
- `program_validate`: validate one source through `weavec --frontend`.
- `program_build`: build an explicit ordered document set from one revision.

`program_build` never silently includes all project documents. The primary source
is first; additional sources retain supplied order; duplicates are rejected.

## Revisioned named targets

- `build_target_set`: create/update target metadata.
- `build_target_list`: list targets at branch head or exact revision.
- `build_target_get`: read one target.
- `build_target_delete`: delete one target in a new revision.
- `build_target_validate`: validate target metadata and ordered sources.
- `build_target_build`: compile the exact revisioned target.

Recommended multi-document flow:

```text
program_source_list
→ build_target_set
→ structural edits
→ build_target_validate
→ branch_merge_preflight
→ review target policy, impact, coverage, and validation_set
→ branch_merge using returned publication_arguments
→ build_target_build
→ build_get
```

## Structural writes

Single-node tools:

- `node_create_form(parent_id, head, position)`;
- `node_add_atom(parent_id, kind, value, position)`;
- `node_set_atom(node_id, value)`;
- `node_move(node_id, new_parent_id, position)`;
- `node_wrap(node_id, head)`;
- `node_delete(node_id)`.

Each successful single-node write publishes one immutable revision.

`node_apply_batch` accepts 1–256 flat operations using the same six kinds.
Temporary aliases created with `as="name"` are referenced as `@name` later in the
same request. `expected_revision_id` provides optimistic concurrency. The entire
batch validates and publishes as one revision with ordered audit rows, or rolls
back completely. See [`edit-transactions.md`](edit-transactions.md).

## Inspection and context

### `node_inspect`

Reads a bounded annotated subtree from branch head or explicit immutable
`revision_id`. The response reports both inspected and current branch-head
revision IDs. Historical inspection is preferred for mapped failed-build
repair. See [`revision-node-inspection.md`](revision-node-inspection.md).

### `revision_diff_page`

Compares one document across two project-owned immutable revisions through stable
IDs. Change kinds include add/remove, kind/head/value, parent/position, and child
count. Page sizes are 1–200 and immutable revision selection makes continuation
stable. See [`revision-diff.md`](revision-diff.md).

Other reads:

- `node_find`: locate stable IDs by head, kind, or exact value;
- `build_diagnostics_page`: bounded mapped diagnostics from verified builds;
- `context_add`: publish scoped immutable design context;
- `context_get`: retrieve context visible at current revision.

## Builds and diagnostics

`build_get` verifies manifest format, build identity, path containment, regular
files, expected artifact set, and every SHA-256 hash before returning paths.
Successful cache admission additionally requires build-key v4, valid compiler
protocols, zero return code, and complete source/map/diagnostic/executable data.

`build_diagnostics_page(build_id, start_index=0, limit=50)` verifies the immutable
build and retained diagnostic document before returning mapped entries. Limits
are 1–200. Raw malformed evidence remains only in verified artifacts.

## Failure and publication semantics

- Rejected edits and batches do not advance branches.
- Policy and policy-history reads do not mutate state.
- Merge preflight, preview, impact, and validation do not publish revisions.
- Policy, coverage, compiler, conflict, and stale-evidence failures publish no
  merge revision.
- Merge publication atomically rechecks both captured branch heads.
- Builds never advance branches.
- A final executable exists only after compiler process and protocol success.
- Build work uses temporary sibling directories and atomic verified publication.
- Program execution remains separate from compilation.

## Configuration

| Variable | Purpose |
|---|---|
| `WEAVE_DB_PATH` | SQLite program database |
| `WEAVE_BUILD_ROOT` | Immutable verified build artifact root |
| `WEAVEC_BIN` | Compiler used for validation and builds |
| `WEAVEC_SOURCE_ROOT` | Compiler checkout used by grammar help |
