# Revisioned agent checkpoints

## Purpose

A branch history records what changed, but it does not necessarily explain what an
agent was trying to accomplish, what it considers complete, what remains, which
questions are unresolved, or which validation evidence already exists.

Jacquard checkpoints provide a bounded structured handoff that is stored with the
same immutable revision history as the program.

The public tools are:

```text
branch_checkpoint_create
branch_checkpoint_get
```

`branch_resume_snapshot` includes the checkpoint resolved from the same selected
revision in `agent_checkpoint`.

## Checkpoint format

The stored canonical JSON format is:

```text
weave-agent-checkpoint-v1
```

A checkpoint contains:

- `objective`: the specific outcome currently being pursued;
- `summary`: the current state and important reasoning needed for a handoff;
- `status`: one of `in_progress`, `blocked`, `ready_for_review`, or `complete`;
- `completed`: concrete finished work;
- `next_steps`: concrete actions that remain;
- `open_questions`: unresolved decisions, risks, or uncertainties;
- `validation`: tests, checks, evidence, or review already performed.

The fields are intended to transfer executable context, not conversational
transcripts. Items should be specific, truthful, non-duplicated, and useful to a
new agent.

## Publication

```text
branch_checkpoint_create(
  project,
  objective,
  summary,
  branch = "main",
  status = "in_progress",
  completed = optional list,
  next_steps = optional list,
  open_questions = optional list,
  validation = optional list,
  expected_revision_id = optional,
  author = "agent")
```

Prepared handoffs should pass the exact branch revision the publishing agent
reviewed as `expected_revision_id`.

A successful response includes:

- `base_revision_id`;
- the new checkpoint `revision_id`;
- `checkpoint_revision_id` and `checkpoint_id`;
- the verified `checkpoint_hash`;
- the normalized `checkpoint` object;
- `resume` arguments for `branch_resume_snapshot` pinned to the checkpoint
  revision.

Checkpoint publication creates a new immutable revision but does not alter the
program state. Its revision root hash is therefore equal to the captured base
revision root hash.

## Atomicity

Checkpoint publication reuses Jacquard's atomic content-document transaction.
Under one SQLite write transaction it:

1. rechecks the captured branch head;
2. inserts or reuses the content-addressed checkpoint document;
3. writes the `create_agent_checkpoint` operation and verified payload;
4. links inherited and new documents to the new revision;
5. publishes the immutable revision snapshots;
6. conditionally advances the branch.

Every consequence commits or rolls back together. A stale attempt cannot leave a
checkpoint document, revision, operation, revision-document link, or branch
update.

The operation payload records:

- `format`;
- `document_id`;
- `checkpoint_hash`;
- status;
- objective.

The authoritative checkpoint remains the verified canonical document rather than
an unbounded operation payload.

## Bounds

Checkpoint input is bounded synchronously:

- objective: at most 2,000 characters;
- summary: at most 16,000 characters;
- each list: at most 64 items;
- each list item: at most 2,000 characters.

Objective, summary, and every supplied item must be non-empty strings. Duplicate
items in one list are rejected.

These limits keep one-call handoffs usable by agents while preventing checkpoint
publication from becoming an unbounded document-ingestion path.

## Resolution

```text
branch_checkpoint_get(
  project,
  branch = "main",
  revision_id = optional)
```

Omitting `revision_id` selects the current branch head. Supplying a project-owned
immutable revision selects that historical state.

Resolution walks `parent1_id` beginning at the selected revision and returns the
newest reachable checkpoint. It does not search descendants, second-parent
history, unrelated branches, or later branch heads.

The response distinguishes:

- `revision_id`: the immutable revision selected for the read;
- `branch_head_revision_id`: the branch's current head at call time;
- `checkpoint_revision_id`: the revision that actually published the resolved
  checkpoint;
- `checkpoint_is_selected_revision`: whether the checkpoint was published on the
  selected revision itself.

A later program revision may inherit an earlier checkpoint. In that case the
focused read reports the later selected revision but its `resume` arguments remain
pinned to `checkpoint_revision_id`.

When no checkpoint is reachable, the response returns `configured=false`, a null
checkpoint, and no resume arguments.

## Integrity verification

Checkpoint reads verify:

- the operation format;
- non-empty document ID and checkpoint hash;
- document existence;
- project scope and fixed checkpoint title;
- JSON object shape;
- normalized field format and bounds;
- recomputed checkpoint hash against the operation payload.

Malformed, tampered, or incorrectly scoped stored state returns
`INVALID_AGENT_CHECKPOINT` instead of silently presenting untrusted handoff data.

## Resume snapshot integration

`branch_resume_snapshot` resolves `agent_checkpoint` using the same exact
`revision_id` used for program documents, targets, policy, contexts, operations,
and first-parent history.

This preserves two important properties:

- a historical snapshot never borrows a later checkpoint;
- a later state may inherit an older checkpoint, but the checkpoint's own resume
  arguments remain pinned to its publishing revision.

The complete checkpoint view participates in `snapshot_id`. Publishing a new
checkpoint therefore changes the deterministic orientation identity even when
program source is unchanged.

## Recommended workflow

Before handoff or stopping:

```text
review branch head
→ branch_checkpoint_create(expected_revision_id = reviewed head)
→ transfer project, branch, and checkpoint revision
```

After restart or transfer:

```text
branch_resume_snapshot(revision_id = checkpoint revision)
→ review agent_checkpoint and immutable project evidence
→ branch_create_at_revision when a separate continuation branch is needed
→ continue structural work with expected_revision_id
```

Use `branch_checkpoint_get` when only the structured handoff is needed. Use
`branch_resume_snapshot` when the receiving agent also needs program, target,
policy, context, operation, history, and branch orientation.

## Errors

- `INVALID_AGENT_CHECKPOINT`: invalid fields, bounds, status, stored format, JSON,
  scope, title, operation metadata, or hash;
- `INVALID_EXPECTED_REVISION_ID`: malformed optimistic-concurrency input;
- `STALE_BRANCH_HEAD`: the selected branch no longer matches the reviewed base;
- normal not-found errors for missing projects, branches, revisions, or checkpoint
  documents.

No partial checkpoint response or partial publication is returned on failure.

## Compatibility

The feature introduces no database schema or migration. Checkpoints reuse existing
content-addressed documents, revision-document links, immutable revisions, and
operation rows.

There is no compiler, bootstrap, build-key, manifest, node-ID, stored compiler
protocol, or Weave language change.

## Qualification

Direct tests prove:

- checkpoint revisions preserve the exact program root hash;
- canonical publication and operation/document linkage;
- exact first-parent historical resolution;
- inherited checkpoint behavior after later program edits;
- unconfigured state;
- stale rollback with no persistent rows;
- all structured field bounds and duplicate rejection;
- tampered-document rejection;
- deterministic resume-snapshot composition.

The production stdio lifecycle publishes two checkpoints around a real structural
edit, resolves current and historical handoffs, verifies snapshot integration,
rejects stale and invalid requests, and inspects SQLite afterward for exact root
relationships, operation links, two retained checkpoint documents, and zero
orphan documents.

Standard CI retains `agent-checkpoint-trace.json`. The packaged `weavec` workflow
ensures the final checkpoint and snapshot registration does not regress compiler,
build, merge, policy, preflight, or artifact-discovery behavior.
