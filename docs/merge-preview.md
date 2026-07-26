# Two-phase branch merge previews

## Purpose

`branch_merge_preview` lets an agent review a stable-ID three-way merge before
publishing a merge revision. The preview is read-only and binds the reviewed
state into a deterministic token. Passing that token to `branch_merge` makes the
publication fail if either branch advanced after review.

This is a concurrency and traceability contract, not merely a dry-run display.

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

## Conflict preview

A semantic stable-ID conflict is a successful preview response with:

```text
mergeable = false
conflicts = exact conflict paths
merged_root_hash = null
```

Conflicts do not mutate the target branch. Passing that current preview ID to
`branch_merge` returns `MERGE_CONFLICT` and still publishes nothing.

## Reviewed publication

```text
branch_merge(
  project,
  target_branch,
  source_branch,
  preview_id,
  author = "merge-agent",
)
```

When `preview_id` is supplied, Jacquard recomputes the preview from the current
heads. A mismatched token returns `STALE_MERGE_PREVIEW` before merge publication.

For a matching clean preview, the target and source heads are checked again
inside the same SQLite `BEGIN IMMEDIATE` transaction that writes the merge
revision. The target branch update also uses compare-and-set semantics. Therefore
an intervening writer cannot publish a merge based on heads different from those
reviewed.

A successful response records:

- the new merge revision;
- target and source branches;
- changed documents;
- the enforced preview ID;
- reviewed base, target-head, and source-head revisions.

The merge revision stores the reviewed common ancestor and both parent heads in
its immutable operation payload. Its first parent is the reviewed target head and
its second parent is the reviewed source head.

## Compatibility

`branch_merge` still accepts calls without `preview_id`. This preserves existing
clients. The merge implementation nevertheless captures both current heads and
rechecks them atomically during publication, so even direct merges are protected
against concurrent branch advancement.

Preview-first merging is recommended for independent agent branches because it
provides explicit review evidence and deterministic stale-state rejection.

## Recommended workflow

```text
branch_merge_preview
→ inspect conflicts and document consequences
→ node_inspect / revision_diff_page when deeper review is needed
→ branch_merge(preview_id = reviewed preview)
→ program_validate / build_target_validate
→ program_build / build_target_build
```

A clean structural merge is not proof of semantic correctness. Validation and
relevant tests still follow merge publication.
