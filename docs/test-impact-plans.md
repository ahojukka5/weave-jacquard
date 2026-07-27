# Exact-revision behavioral-test impact plans

Jacquard can explain which revisioned behavioral tests are structurally affected
between two immutable project revisions before an agent chooses an explicit test
batch.

The impact plan is a read-only evidence product. It does not run the compiler,
execute tests, mutate a branch, or claim that the selected tests are sufficient
for semantic correctness.

## Workflow

Compare one explicit base revision with one exact target revision:

```text
test_impact_plan(
  project = "demo",
  base_revision_id = "<base-revision>",
  branch = "main",
  target_revision_id = "<target-revision>",
  limit = 50,
  evidence_limit = 100
)
```

When `target_revision_id` is omitted, Jacquard captures the current branch head
once and returns the exact captured revision. Subsequent pages should reuse that
returned target revision rather than reading a moving branch head again.

## Structural candidate rules

A test that still exists at the target revision becomes an impacted candidate
when at least one of these facts is true:

1. its revisioned test definition changed;
2. its referenced named build-target definition changed;
3. one or more source documents referenced by that target changed.

Reasons are returned in deterministic order as:

- `test_definition_changed`;
- `build_target_changed`;
- `source_changed`.

Each candidate includes the exact target-revision `definition_hash`, referenced
build target, complete target document list, changed source documents, and a
focused `test_target_get` call.

These are structural dependency rules, not code-understanding heuristics. A
source change can be irrelevant to the observed behavior, while a semantic
relationship outside the declared target graph can remain invisible to the
plan.

## Separate gap evidence

Objects that cannot be executed as surviving target-revision tests are not mixed
into the candidate list. The plan reports separately:

- removed test targets;
- removed build targets;
- changed source documents referenced by no surviving test candidate;
- changed surviving build targets referenced by no surviving test.

Every evidence collection has an exact total, returned count, and truncation
flag. `evidence_limit` bounds each returned collection independently.

A removed test is historical change evidence, never a runnable candidate. An
uncovered source or untested target is a review gap, not proof that the change is
unsafe or that a new test must be added.

## Stable plan identity

`plan_id` is a deterministic SHA-256 identity over the exact comparison and its
complete unpaginated structural evidence, including:

- project and branch labels;
- exact base and target revision IDs;
- full state hashes for both revisions;
- changed source, target, and test metadata;
- removed objects and uncovered gaps;
- every impacted test and its reasons.

The same exact comparison returns the same `plan_id` across lexical pages.
Changing either revision or any underlying structural evidence changes the plan
identity.

## Lexical pagination

Impacted tests are ordered lexically by test-target name. Pagination uses
`start_after_name` and returns `next_after_name` when more candidates remain.

Lexical order exists only for deterministic continuation. It must not be
interpreted as:

- priority or urgency;
- expected failure probability;
- execution cost;
- business importance;
- preferred repair order.

A page is not a complete selection unless `complete_selection = true`.

## Bridge to explicit execution

When all impacted candidates fit in the first page and the selection is
non-empty, the response includes an exact replayable call:

```text
{
  "tool": "test_batch_run",
  "arguments": {
    "project": "demo",
    "test_targets": ["candidate-a", "candidate-b"],
    "branch": "main",
    "revision_id": "<exact-target-revision>"
  }
}
```

The call preserves the complete lexical candidate list and exact target
revision. It does not execute automatically.

No batch call is emitted for:

- an empty candidate plan;
- a truncated first page;
- any continuation page.

For a paginated plan, the caller must collect every page under the same
`plan_id`, verify the exact target revision, construct the complete explicit
selection, and then call `test_batch_run` deliberately.

## Interpretation limits

An impact plan is structural candidate evidence only. It is not:

- test execution evidence;
- proof that selected tests pass;
- proof that selected tests fully cover the change;
- compiler or merge-preflight evidence;
- merge publication permission;
- automatic test-selection policy;
- a claim about unselected tests;
- semantic dependency inference beyond declared test-to-target-to-source links.

The authoritative result of execution remains the individual immutable run and
explicit batch evidence described in `sandboxed-test-runs.md` and
`explicit-test-batches.md`.
