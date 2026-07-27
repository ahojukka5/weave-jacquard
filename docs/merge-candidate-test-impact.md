# Virtual merge-candidate behavioral-test impact plans

Jacquard can explain which revisioned behavioral tests are structurally affected
by one exact clean branch-merge preview before publishing the merge.

The plan compares the committed target head with the preview's in-memory merged
state. It runs no compiler or test, creates no project revision, and advances
neither branch.

## Workflow

Create and inspect a merge preview first:

```text
preview = branch_merge_preview(
  project = "demo",
  target_branch = "main",
  source_branch = "feature"
)

branch_merge_test_impact(
  project = "demo",
  target_branch = "main",
  source_branch = "feature",
  preview_id = preview.preview_id,
  limit = 50,
  evidence_limit = 100
)
```

Supplying `preview_id` binds the request to the exact target and source heads
used by the preview. If either head changes, Jacquard recreates the preview and
returns `STALE_MERGE_PREVIEW` rather than mixing old review evidence with a new
candidate.

A conflicted preview returns the structural merge conflict before any test-impact
plan is produced.

## Exact candidate identity

Every page binds:

- project, target branch, and source branch;
- exact common-base revision;
- exact target-head and source-head revisions;
- deterministic `preview_id`;
- deterministic merged-state root hash;
- deterministic `plan_id` over the complete unpaginated impact evidence.

The merged state exists only in memory. It is not a committed revision and must
not be represented as one.

## Structural candidate rules

A test that survives in the virtual merged state becomes an impacted candidate
when at least one of these facts is true relative to the committed target head:

1. its test-target definition changed;
2. its referenced build-target definition changed;
3. one or more source documents referenced by that build target changed.

Reasons are returned in deterministic order:

- `test_definition_changed`;
- `build_target_changed`;
- `source_changed`.

Each candidate includes the virtual definition hash, referenced target, complete
target document list, changed source documents, and a `definition_subject` that
states:

```text
kind = virtual_merge_candidate
preview_id = <exact-preview-id>
committed_revision_id = null
```

The definition hash identifies in-memory candidate metadata. Ordinary
revision-bound `test_target_get` cannot read it.

## Separate gap evidence

The plan reports separately:

- removed test targets;
- removed build targets;
- changed program documents covered by no surviving impacted test;
- changed surviving build targets referenced by no surviving test.

Each collection has an exact total, returned count, and truncation flag.
`evidence_limit` bounds each collection independently.

Removed tests are historical change evidence, not runnable candidates. Uncovered
sources and untested targets are review gaps, not automatic failure decisions.

## Pagination

Impacted candidates are ordered lexically by test-target name. Pagination uses
`start_after_name` and returns `next_after_name` when more candidates remain.
Every page for the same exact preview and evidence graph returns the same
`plan_id`.

Lexical order is deterministic continuation only. It is not priority, urgency,
expected failure probability, cost, or recommended repair order.

## Execution boundary

The response intentionally contains:

```text
candidate_execution = null
```

Existing `test_batch_run` accepts an immutable committed revision ID. A virtual
merged state has no such revision, so emitting ordinary batch arguments would
falsely claim that the preview can be executed through the revision-bound path.

This capability therefore provides planning evidence only. A future candidate
execution service must retain its own evidence identity bound to the preview ID,
merged root hash, compiler, executable, sandbox policy, definitions, and observed
behavior. It must still publish no merge.

## Interpretation limits

A virtual merge-candidate impact plan is not:

- compiler validation;
- test execution evidence;
- proof that selected tests pass;
- proof of complete semantic coverage;
- merge-preflight admission;
- permission to publish the merge;
- automatic ranking or test-selection policy;
- a claim about unselected tests.

After the source branch or target branch changes, callers must create a new
preview and a new impact plan. After a real merge publication, callers must use
committed-revision workflows rather than treating the old virtual candidate as a
revision.
