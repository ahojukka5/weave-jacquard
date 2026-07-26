# Two-phase branch merge previews

## Purpose

`branch_merge_preview` lets an agent review a stable-ID three-way merge before
publishing a merge revision. The preview is read-only and binds the reviewed
state into a deterministic token. Passing that token to merge validation and
publication makes the workflow fail if either branch advances.

This is a concurrency and traceability contract, not merely a dry-run display.
Compiler validation of the clean candidate is specified separately in
[`merge-validation.md`](merge-validation.md).

## Preview request

```text
branch_merge_preview(
  project,
  target_branch,
  source_branch,
)
```

The service resolves:

- the current target head;
- the current source head;
- their common ancestor;
- the validated stable-ID merge result, or exact conflict paths.

Neither branch is checked out, advanced, or modified.

## Preview identity

The response format is `weave-merge-preview-v1`. `preview_id` is the canonical
SHA-256 identity of:

```text
format
+ project
+ target branch name
+ source branch name
+ common ancestor revision
+ target head revision
+ source head revision
```

The same project, direction, and branch heads produce the same preview ID.
Changing either head, reversing merge direction, or selecting another project
produces a different ID.

No preview rows are stored in the database. Immutable revision IDs make the
preview reproducible, while the token proves which branch state was reviewed.

## Clean preview

A clean preview returns:

- `mergeable: true`;
- target, source, and base revision IDs;
- target and source root hashes;
- the prospective merged root hash;
- changed document names;
- compact per-document consequences.

Each changed document reports:

- `added`, `removed`, or `modified` status;
- before and after document hashes;
- before and after node counts;
- number of changed stable nodes;
- aggregate stable-node change kinds.

The change kinds follow `revision_diff_page`: additions, removals, kind/head/value
changes, parent and position changes, and child-count changes. Complete trees are
not returned. Use `node_inspect` or `revision_diff_page` when deeper local review
is required.

The internal clean candidate remains available only to Jacquard services. It is
never returned as an unbounded MCP tree and is not stored as a temporary
revision.

## Conflict preview

A semantic stable-ID conflict is a successful preview response with:

```text
mergeable = false
conflicts = exact conflict paths
merged_root_hash = null
```

Conflicts do not mutate the target branch. Passing that current preview ID to
`branch_merge_validate` or `branch_merge` returns `MERGE_CONFLICT` and still
publishes nothing.

## Candidate validation

```text
branch_merge_validate(
  project,
  target_branch,
  source_branch,
  build_target,
  preview_id = reviewed preview,
)
```

Validation recomputes the preview, resolves the named target from the exact
in-memory merged state, renders its ordered canonical sources, and invokes
`weavec --frontend`. It creates no revision and retains no build artifact.

A stale token returns `STALE_MERGE_PREVIEW`. A clean compiler result returns a
deterministic validation identity plus source, compiler, and WIR hashes. Compiler
unavailability or rejection is reported without changing either branch.

## Reviewed and validated publication

```text
branch_merge(
  project,
  target_branch,
  source_branch,
  preview_id,
  validation_target,
  author = "merge-agent",
)
```

When `validation_target` is supplied, Jacquard repeats exact-candidate validation
before publication. This repetition is intentional: a prior validation response
is evidence, not a bearer token that can bypass the compiler.

The validation result supplies the preview ID used for publication. The target
and source heads are then checked again inside the same SQLite
`BEGIN IMMEDIATE` transaction that writes the merge revision. The target branch
update also uses compare-and-set semantics.

The workflow therefore closes both concurrency windows:

- an intervening writer before validation changes the preview ID;
- an intervening writer during or after validation fails the transactional head
  check.

A successful response records:

- the new merge revision;
- target and source branches;
- changed documents;
- the enforced preview ID;
- reviewed base, target-head, and source-head revisions;
- validation target and complete bounded validation evidence.

The merge revision stores the reviewed common ancestor and both parent heads in
its immutable operation payload. Its first parent is the reviewed target head and
its second parent is the reviewed source head.

## Failure behavior

- `MERGE_CONFLICT`: the stable-ID three-way merge is not clean;
- `STALE_MERGE_PREVIEW`: the reviewed heads no longer match current heads;
- `MERGE_VALIDATION_UNAVAILABLE`: the authoritative compiler is unavailable;
- `MERGE_VALIDATION_FAILED`: the compiler rejects or times out on the candidate.

Every failure leaves the target branch unchanged.

## Compatibility

`branch_merge` still accepts calls without `preview_id` or `validation_target`.
This preserves existing clients. The merge implementation nevertheless captures
both current heads and rechecks them atomically during publication, so even
direct merges are protected against concurrent branch advancement.

Preview-and-validation-first merging is recommended for independent agent
branches because it provides explicit review evidence, authoritative semantic
proof, and deterministic stale-state rejection.

## Recommended workflow

```text
branch_merge_preview
→ inspect conflicts and document consequences
→ node_inspect / revision_diff_page when deeper review is needed
→ branch_merge_validate(build_target, preview_id)
→ branch_merge(preview_id, validation_target)
→ build_target_build
```

A clean structural merge is not proof of semantic correctness. The compiler gate
now runs before publication; native build and execution may still follow the
published immutable revision when required.
