# Stable project merge queues

## Purpose

A project can have many active branches, each with different program changes,
checkpoints, and merge relationships to a target branch. Reviewing every source
through separate branch-list, checkpoint, and merge-preview calls makes it easy
to mix branch heads from different project moments.

`project_merge_queue_page` provides one bounded read-only source-to-target view
within one exact branch-head catalog.

The queue is supervisory evidence. It does not publish a merge and does not
replace merge preflight.

## Request

```text
project_merge_queue_page(
  project,
  target_branch = "main",
  start_after_source = optional,
  catalog_id = optional,
  limit = 10,
  checkpoint_scan_limit = 100,
  conflict_limit = 20,
  changed_document_limit = 50)
```

The target branch must exist in the current project catalog. Every other branch
is a source candidate.

## Response format and identity

The response format is:

```text
weave-project-merge-queue-v1
```

`page_id` hashes the complete returned page. Repeating the same request against
the same exact branch-head catalog and stored evidence produces the same page
identity.

`catalog_id` hashes:

- the selected target branch and its exact head revision;
- every source branch name and exact head revision, in lexical order.

The catalog therefore changes when any branch is added, removed, or advances.

## Stable catalog paging

Source branches are ordered lexically by branch name. This order exists only for
deterministic paging.

The first page omits `catalog_id`. When `has_more` is true, continue with:

```text
start_after_source = next_after_source
catalog_id = previous catalog_id
```

`start_after_source` is an exclusive lexical cursor and must identify a source
branch in the exact catalog.

If the target head or any source catalog member changes before continuation, the
request returns:

```text
STALE_PROJECT_MERGE_QUEUE_CATALOG
```

The caller must restart from the first page. Jacquard does not silently combine
merge previews from different branch-head sets.

The catalog contains at most 1,000 branches. Larger projects return
`MERGE_QUEUE_BRANCH_FANOUT_EXCEEDED` instead of building an unbounded in-memory
catalog.

## Source classifications

Each source entry reports one structural classification:

- `clean_changes`: stable-ID merge composition succeeded and changes at least one
  document relative to the exact target head;
- `clean_no_changes`: stable-ID merge composition succeeded and produces no
  document change relative to the exact target head;
- `conflicted`: stable-ID merge composition failed with one or more conflicts.

`mergeable` is true for both clean classifications and false for `conflicted`.

These classifications describe only the deterministic merge preview. They do
not describe policy admission, compiler correctness, target coverage, human
priority, or publication readiness.

## Exact merge identity

Every source entry includes:

- source branch and exact source head revision;
- selected target head revision at page level;
- exact common-base revision;
- deterministic `preview_id`;
- target and source root hashes;
- merged root hash when structurally mergeable;
- conflict and changed-document totals.

The service obtains a normal `branch_merge_preview` and verifies that its target
and source heads still match the catalog. If either head changes while a page is
being composed, the request fails with the stale-catalog error.

The queue never presents a preview under a head identity that it did not review.

## Bounded compact evidence

Public maximums are:

- 20 source entries per page;
- 500 first-parent revisions scanned for checkpoint evidence per returned source;
- 100 returned conflict strings per source;
- 200 returned changed-document names per source.

Each source reports complete totals and truncation flags:

- `conflict_count`, `conflicts`, and `conflicts_truncated`;
- `changed_document_count`, `changed_documents`, and
  `changed_documents_truncated`.

The compact queue intentionally omits the full node-level document-change
summaries returned by `branch_merge_preview`. Use the replayable full-preview
call when detailed merge inspection is required.

Invalid bounds return `INVALID_PROJECT_MERGE_QUEUE_LIMIT`.

## Source checkpoint evidence

Each source entry contains a compact `source_checkpoint` view produced from the
same exact source head. It reports:

- checkpoint search state;
- whether a found checkpoint is the source head;
- verified compact checkpoint evidence;
- revisions scanned;
- exact revisions since a found checkpoint;
- scan-limit and complete-history evidence;
- a lag lower bound when older history remains unscanned;
- program-root drift since a found checkpoint.

Checkpoint search is independently bounded by `checkpoint_scan_limit` and uses
the existing verified revisioned checkpoint protocol.

Checkpoint evidence is context for review. It does not determine queue order or
merge readiness.

## Replayable follow-up calls

Every source entry contains:

```text
full_preview.tool = branch_merge_preview
full_preview.arguments = {project, target_branch, source_branch}
```

This recovers complete deterministic document and node-change evidence for the
current catalog heads.

Structurally mergeable entries additionally contain:

```text
preflight.tool = branch_merge_preflight
preflight.arguments = {
  project,
  target_branch,
  source_branch,
  preview_id
}
```

Conflicted entries return `preflight = null`, because preflight cannot validate a
merge candidate that does not structurally compose.

The caller may need to add an explicit uncovered-document override only through
the normal preflight interface and only when the target merge policy permits it.
The queue does not invent that choice.

## Structural mergeability is not readiness

A true `mergeable` value proves only that:

- a common base was found;
- stable-ID merge composition succeeded;
- the merged state passed structural semantic validation;
- the returned preview corresponds to the exact catalog heads.

It does not prove:

- target merge-policy admission;
- changed-document coverage by named build targets;
- compiler validation of affected targets;
- required preflight identity;
- unchanged source and target heads at publication time;
- human approval or intended priority.

Run the returned preflight call before publication. Publication must continue to
use the normal reviewed preview/preflight and compare-and-set head checks.

## Ordering is not priority

Lexical source order is deterministic pagination only. It does not represent:

- merge priority or urgency;
- branch age;
- amount or quality of work;
- checkpoint freshness;
- correctness;
- policy or compiler readiness.

Consumers must not promote the first returned source merely because it appears
first.

## Read-only behavior

`project_merge_queue_page` creates no:

- branch or revision;
- operation row;
- document or revision-document link;
- build or compiler artifact;
- filesystem output;
- merge publication.

The service recomputes previews and checkpoint evidence from committed immutable
state only.

## Errors

- `INVALID_MERGE_QUEUE_TARGET`: selected target is not a catalog branch;
- `INVALID_MERGE_QUEUE_CURSOR`: cursor or optional ID is malformed, or the source
  cursor is not a catalog member;
- `STALE_PROJECT_MERGE_QUEUE_CATALOG`: supplied catalog differs from current exact
  branch heads, including a race during page composition;
- `INVALID_PROJECT_MERGE_QUEUE_LIMIT`: a public bound is invalid;
- `MERGE_QUEUE_BRANCH_FANOUT_EXCEEDED`: project exceeds the explicit branch
  catalog maximum;
- normal checkpoint verification errors: stored source-checkpoint evidence is
  malformed or tampered;
- normal merge-preview errors: exact source-to-target structural preview cannot
  be constructed for reasons other than a reported merge conflict.

No partial page is returned on request-level failure.

## Qualification

Direct tests prove:

- deterministic page and catalog identity;
- lexical stable two-page continuation;
- clean-change, conflict, and exact no-change classifications;
- changed-document truncation and conflict evidence;
- checkpoint-at-head and checkpoint-behind-head evidence;
- complete replayable preview and preflight arguments;
- stale-catalog rejection after source and target advances;
- target, cursor, ID, and bound validation;
- branch-catalog fanout protection;
- shared production preview and checkpoint-status construction.

The production stdio lifecycle creates clean, conflict, and no-change source
branches against one target, replays the returned full-preview call, verifies all
queue reads preserve branch heads, advances one source, rejects the old catalog,
and refreshes to new exact evidence.

Standard CI retains `project-merge-queue-trace.json`. The packaged `weavec`
workflow verifies that final MCP registration does not regress native builds,
merge publication, policy, preflight, checkpoint, resume, timeline, comparison,
agent status, or artifact discovery.

## Compatibility

The feature is additive and read-only. It reuses existing immutable revisions,
branch heads, merge-preview format, checkpoint documents, and preflight tools.

It changes no database schema, checkpoint format, merge-preview format, build
key, manifest, node ID, compiler protocol, or Weave language rule.
