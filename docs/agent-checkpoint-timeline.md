# Agent checkpoint timelines and progress comparison

## Purpose

A single checkpoint explains one handoff. Long-running or multi-agent work also
needs a bounded way to inspect how handoffs evolved and to compare two exact
checkpoint states without replaying every branch revision manually.

Jacquard provides two read-only supervisory tools:

```text
branch_checkpoint_history_page
branch_checkpoint_compare
```

Both reuse the verification rules of `weave-agent-checkpoint-v1`. Neither tool
creates or advances program state.

## Bounded checkpoint history

```text
branch_checkpoint_history_page(
  project,
  branch = "main",
  start_revision_id = optional,
  limit = 20,
  revision_scan_limit = 200)
```

Omitting `start_revision_id` begins at the selected branch's current head.
Supplying it begins at one exact project-owned immutable revision.

The history follows only `parent1_id` and returns verified checkpoints in
newest-to-oldest order.

### Why two limits are required

Checkpoints may be sparse. A page that limits only returned checkpoints could
still walk an unbounded number of ordinary revisions before finding them.

Each call therefore has two independent bounds:

- `limit`: maximum returned checkpoints, from 1 through 50;
- `revision_scan_limit`: maximum first-parent revisions inspected, from 1 through
  500.

The scan stops when either bound is reached or first-parent history ends.

The response reports:

- `returned_checkpoint_count`;
- `scanned_revision_count`;
- `checkpoint_limit_reached`;
- `scan_limit_reached`;
- `has_more`;
- exact `next_revision_id`.

When `has_more=true`, pass `next_revision_id` as the next call's
`start_revision_id`. It identifies the first unscanned immutable revision. It is
not a mutable page number or an offset into a changing branch head.

### Page identity

The response format is:

```text
weave-agent-checkpoint-timeline-v1
```

`page_id` is the canonical hash of the complete returned page before that ID is
added. Repeating the same immutable start, bounds, and database evidence produces
the same ID.

The response separately reports:

- `branch_head_revision_id`, current comparison metadata;
- `start_revision_id`, the immutable history actually scanned;
- `start_is_branch_head`.

A branch may advance after an earlier page. Continuation remains stable because it
uses the returned immutable `next_revision_id`.

## Timeline entries

Each compact entry contains:

- `checkpoint_revision_id`;
- verified checkpoint document ID and hash;
- revision timestamp, author, and program root hash;
- checkpoint status and objective;
- SHA-256 and up to 512 characters of summary preview;
- explicit summary truncation;
- counts for completed work, next steps, open questions, and validation;
- a complete `branch_resume_snapshot` call containing project, branch, and exact
  checkpoint revision.

The full summary and structured lists remain available through
`branch_checkpoint_get` or `branch_resume_snapshot`. The timeline avoids repeating
up to 64 bounded items for every historical checkpoint.

## Exact progress comparison

```text
branch_checkpoint_compare(
  project,
  base_checkpoint_revision_id,
  target_checkpoint_revision_id)
```

Both arguments must be exact project-owned revisions that themselves published
checkpoints. A normal program revision that merely inherits a checkpoint is not a
valid endpoint.

The response format is:

```text
weave-agent-checkpoint-comparison-v1
```

`comparison_id` hashes the complete deterministic comparison.

### Endpoint evidence

Both `base` and `target` include:

- checkpoint revision, document, and hash;
- program root hash;
- timestamp and author;
- status and objective.

`program_state_changed` compares the two immutable revision root hashes. It does
not inspect or summarize source-level differences; use revision diff and render
tools for that work.

### Scalar differences

The comparison reports:

- base and target status plus `changed`;
- base and target objective plus `changed`;
- summary SHA-256 values, bounded previews, character counts, truncation, and
  `changed`.

Summary bodies remain bounded by the checkpoint protocol, but the comparison uses
previews and hashes to keep one supervisory result compact.

### Ordered list differences

For each structured list:

- `completed`;
- `next_steps`;
- `open_questions`;
- `validation`;

the comparison reports:

- base and target counts;
- `added`, preserving target order;
- `removed`, preserving base order;
- `changed`.

Checkpoint lists reject duplicates at publication, so ordered set differences are
unambiguous.

## No semantic inference

The comparison deliberately reports structural evidence only.

A removed item does not by itself prove:

- a next step was completed;
- an open question was resolved;
- validation became invalid;
- completed work was undone.

Agents and reviewers must interpret removals using checkpoint summaries, program
changes, validation evidence, and project context.

The names `base` and `target` also do not establish ancestry or chronology. The
tool accepts any two project-owned checkpoint revisions, including checkpoints on
independent branches. It does not claim the base is a first-parent ancestor of the
target.

## Integrity

Timeline and comparison reads verify the same checkpoint evidence as focused
checkpoint reads:

- operation format and required identifiers;
- document existence, project scope, and fixed title;
- canonical JSON structure and field bounds;
- recomputed checkpoint hash.

Corrupt or tampered checkpoint evidence returns `INVALID_AGENT_CHECKPOINT`.

A comparison endpoint without an exact checkpoint operation returns
`CHECKPOINT_REVISION_REQUIRED`.

## Errors

- `INVALID_CHECKPOINT_TIMELINE_LIMIT`: invalid checkpoint or revision-scan bound;
- `CHECKPOINT_REVISION_REQUIRED`: a comparison endpoint did not publish a
  checkpoint;
- `INVALID_AGENT_CHECKPOINT`: malformed or tampered checkpoint evidence;
- normal not-found errors for missing projects, branches, or foreign/unknown
  revisions.

No partial comparison is returned on failure. A page may legitimately return zero
checkpoints with `has_more=true` when its revision-scan bound is reached before a
checkpoint is found.

## Recommended supervisory workflow

```text
branch_checkpoint_history_page(limit, revision_scan_limit)
→ review compact handoff sequence
→ continue with next_revision_id while has_more
→ choose exact checkpoint_revision_id values
→ branch_checkpoint_compare(base, target)
→ open selected handoffs with branch_checkpoint_get or branch_resume_snapshot
```

Use a larger `revision_scan_limit` when checkpoints are known to be sparse. Keep
`limit` small when summaries and progress counts are sufficient for orientation.

## Compatibility

The tools are read-only and additive. They reuse existing immutable revisions,
operation rows, content-addressed checkpoint documents, and checkpoint hashes.

There is no database schema/version, checkpoint format, compiler, bootstrap,
build-key, manifest, node-ID, stored compiler protocol, or Weave language change.

## Qualification

Direct tests prove:

- deterministic page identity;
- newest-to-oldest first-parent ordering;
- exact first-unscanned continuation;
- checkpoint and scan-limit stop conditions;
- summary preview truncation;
- complete replayable resume calls;
- exact structural progress deltas;
- same-checkpoint unchanged comparison;
- non-checkpoint endpoint rejection;
- bound validation and foreign-revision rejection.

The production stdio lifecycle publishes three checkpoints around structural
edits, reads two stable pages, proves a scan-limited sparse page, compares the
first and third checkpoints, compares one checkpoint to itself, rejects a normal
program revision, and verifies no history/comparison operation rows were written.

Standard CI retains `agent-checkpoint-timeline-trace.json`. The packaged `weavec`
workflow verifies that final supervisory registration does not regress compiler,
build, merge, policy, preflight, checkpoint, resume, or artifact-discovery
behavior.
