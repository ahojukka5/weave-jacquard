# Working edit candidates

A coding agent should modify an explicit software revision, not an ambiguous
working tree. Working candidates let Jacquard accumulate structural edits,
qualify the exact resulting revision, and publish only that revision.

This is distinct from virtual merge candidates, which qualify an unpublished
three-way merge. Working candidates are sequential edit chains. Merge preflight
remains the admission path for combining two branches.

## Lifecycle

```text
base revision
→ candidate_open
→ entity_list / entity_inspect
→ candidate_apply_batch
→ candidate_qualify
→ candidate_publish | candidate_abandon | candidate_revert_last
```

`candidate_open` records:

- `id`
- `base_revision_id`
- `head_revision_id` (initially the base)
- `status = open`

Edits create new immutable revisions and move only the candidate head. The
selected project branch does not move. Failed operations leave the candidate
and every branch unchanged.

## Qualification

`candidate_qualify` records evidence against the current candidate head:

- `syntactic` — tree integrity for every document in the revision;
- `compiler` — `weavec --frontend` on the canonical candidate sources.

A syntax pass is not compiler qualification. Compiler unavailability is
`unavailable`, not a pass. The record stores compiler identity so a later
compiler change remains visible even if the candidate content is unchanged.

Prior qualification becomes stale when candidate content changes. Inspect
reports `invalidated_by = ["candidate_content_changed"]`. Unrelated candidate
metadata such as the human-readable name is not stored on the qualification
row, so renaming is not possible after open; abandon and reopen instead.

## Publication

`candidate_publish` fail-closes unless:

- the candidate is still open;
- `expected_revision_id`, when supplied, is the current head;
- required qualification, when requested, passed on that exact head and is
  not stale;
- the target branch is still at the candidate base (or the caller-supplied
  expected base).

On success the branch fast-forwards to the candidate head. Jacquard does not
publish first and attach evidence afterwards. A concurrent branch advance
returns `PUBLICATION_RACE`.

## Recovery

- `candidate_revert_last` moves the candidate head to the previous revision in
  its first-parent chain;
- `candidate_abandon` stops further edits without moving a branch;
- `candidate_inspect` returns the edit history needed to replay or debug.

`candidate_replay` applies a recorded operation list, including optional pinned
`node_id` fields, onto a new candidate from the same base.

## Textual boundary

`program_import` remains the textual path for comments, documentation,
formatting, configuration, and migration. Those edits do not inherit
candidate qualification merely because they happened on the same project.
Structural batches and textual imports can coexist; only the structural path
claims stable-ID semantics.

## Errors

Machine-readable codes include:

- `STALE_REVISION`
- `MISSING_STRUCTURAL_TARGET`
- `AMBIGUOUS_TARGET`
- `INVALID_EDIT`
- `CANDIDATE_CONFLICT`
- `QUALIFICATION_FAILURE`
- `STALE_QUALIFICATION`
- `PUBLICATION_RACE`
