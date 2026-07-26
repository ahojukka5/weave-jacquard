# Project agent status pages

## Purpose

Long-running agentic development may have many independent branches. A supervisor
needs a bounded view of each exact branch head and its latest verified handoff
without mixing pages from different branch-head states or assuming that revision
age or checkpoint lag means an agent is inactive.

Jacquard provides:

```text
project_agent_status_page
```

The tool is read-only. It reports structural branch and checkpoint evidence across
one exact current branch-head catalog.

## Request

```text
project_agent_status_page(
  project,
  start_after_branch = optional,
  catalog_id = optional,
  limit = 25,
  checkpoint_scan_limit = 100)
```

Maximums are:

- 100 returned branches per page;
- 500 first-parent revisions scanned per returned branch;
- 1,000 branches in one project catalog.

## Stable branch-head catalog

The service reads project branches in lexical name order and constructs a catalog
from exact members:

```text
{branch, head_revision_id}
```

The catalog format is:

```text
weave-project-agent-status-catalog-v1
```

`catalog_id` is the canonical hash of the complete bounded catalog.

The first page may omit `catalog_id`. Continuation passes both:

- `start_after_branch`, the last returned branch name;
- the returned `catalog_id`.

If a branch is added, removed, or advances before the next page, the catalog hash
changes and the continuation returns `STALE_AGENT_STATUS_CATALOG`. The tool does
not combine branches from two different project states.

`start_after_branch` must identify an exact member of the current catalog. It is
an exclusive lexical cursor, not a row offset.

A project with more than 1,000 branches returns
`AGENT_STATUS_BRANCH_FANOUT_EXCEEDED` rather than constructing an unbounded
catalog.

## Page identity

The response format is:

```text
weave-project-agent-status-v1
```

Each page reports:

- catalog identity and total branch count;
- current cursor and limits;
- returned count;
- `has_more` and `next_after_branch`;
- lexical branch ordering;
- compact branch status entries.

`page_id` hashes the complete returned page. Repeating a page against unchanged
catalog and database evidence produces the same ID.

## Branch-head evidence

Each branch entry identifies its exact `head_revision_id` and compact immutable
head evidence:

- root hash;
- first and second parent revisions;
- message;
- author;
- creation timestamp.

`resume_head` contains a complete `branch_resume_snapshot` call pinned to that
exact head revision.

## Bounded checkpoint search

For each returned branch, the service searches first-parent history beginning at
the exact catalog head. It scans at most `checkpoint_scan_limit` revisions.

The branch reports one `checkpoint_state`:

### `head`

The branch head itself published the latest checkpoint.

### `behind_head`

A verified checkpoint was found behind the branch head. The response reports the
exact number of first-parent revisions between head and checkpoint.

### `not_found_within_scan`

No checkpoint was found within the explicit scan bound, but older history remains.
The response does not claim that the branch has no checkpoint. It reports:

- `checkpoint_scan_limit_reached=true`;
- `checkpoint_lag_lower_bound`, equal to revisions scanned;
- incomplete first-parent-history evidence.

### `none_in_first_parent_history`

The scan reached the root revision without finding a checkpoint. Only this state
claims that complete selected first-parent history contains no checkpoint.

## Checkpoint evidence

When a checkpoint is found, the branch entry contains verified compact evidence:

- checkpoint revision, document, and hash;
- checkpoint revision timestamp, author, and program root hash;
- status and objective;
- counts for completed work, next steps, open questions, and validation;
- a complete `branch_resume_snapshot` call pinned to the checkpoint revision.

The focused checkpoint and resume tools remain available when full summary and
structured lists are needed.

Checkpoint evidence uses the same scope, format, canonical structure, and hash
verification as `branch_checkpoint_get`.

## Structural checkpoint lag

For a found checkpoint, the response reports:

- `checkpoint_is_head`;
- `revisions_since_checkpoint`;
- revisions scanned;
- whether the head root hash differs from the checkpoint revision root hash.

`program_state_changed_since_checkpoint` is exact root-hash evidence. It does not
identify which documents changed or whether those changes are valid. Use revision
diffs and pinned rendering for source-level analysis.

When no checkpoint is found within the scan, exact lag is unknown and
`revisions_since_checkpoint` remains null. The lower-bound field is used instead.

## No activity or quality inference

The service deliberately does not label an agent or branch as:

- active or inactive;
- stale or current;
- blocked;
- complete;
- correct;
- review-ready.

A timestamp is stored revision metadata, not a wall-clock activity judgment.
Checkpoint lag and root-hash drift are structural evidence only. A branch may
legitimately advance many revisions after a checkpoint, or retain an old
checkpoint while work continues elsewhere.

Supervisors should combine this page with checkpoint contents, checkpoint
timelines, comparisons, program validation, build evidence, and merge preflight.

## Errors

- `INVALID_AGENT_STATUS_LIMIT`: invalid page or checkpoint-scan bound;
- `INVALID_AGENT_STATUS_CURSOR`: malformed cursor/catalog input or a cursor not in
  the current catalog;
- `STALE_AGENT_STATUS_CATALOG`: project branch heads changed since the supplied
  catalog was created;
- `AGENT_STATUS_BRANCH_FANOUT_EXCEEDED`: more than 1,000 current branches;
- `INVALID_AGENT_CHECKPOINT`: malformed or tampered checkpoint evidence;
- normal not-found errors for missing projects or revisions.

No partial page is returned on request-level failure.

## Recommended supervisory workflow

```text
project_agent_status_page(limit, checkpoint_scan_limit)
→ review exact branch heads and checkpoint states
→ continue with catalog_id and next_after_branch while has_more
→ open selected branch heads with resume_head
→ open checkpoint revisions with checkpoint.resume
→ inspect checkpoint history or compare exact checkpoints when needed
```

Use a larger checkpoint scan bound only when older handoffs are expected. A small
bound provides explicit lower-bound evidence without turning a project dashboard
into an unbounded history traversal.

## Compatibility

The feature is additive and read-only. It reuses existing branches, immutable
revisions, operations, content-addressed checkpoint documents, and hashes.

There is no database schema/version, checkpoint format, compiler, bootstrap,
build-key, manifest, content-hash envelope, node-ID, stored compiler protocol, or
Weave language change.

## Qualification

Direct tests prove:

- deterministic page and catalog identity;
- lexical two-page continuation;
- checkpoint at head;
- checkpoint behind a changed program head;
- exact checkpoint lag and root-hash drift;
- scan-limited unknown checkpoint state;
- complete history with no checkpoint;
- stale catalog rejection after a head advances;
- invalid bounds and cursors;
- branch-fanout protection.

The production stdio lifecycle creates four branches with distinct checkpoint
states, pages them through one catalog, performs a complete-history follow-up,
advances main, rejects the stale catalog, refreshes to a new catalog, and verifies
that no project-agent-status operation rows were written.

Standard CI retains `project-agent-status-trace.json`. The packaged `weavec`
workflow verifies that final dashboard registration does not regress compiler,
build, merge, policy, preflight, checkpoint, resume, timeline, comparison, or
artifact-discovery behavior.
