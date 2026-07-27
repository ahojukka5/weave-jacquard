# Explicit behavioral test batches

Jacquard can execute a caller-selected set of revisioned behavioral tests and
retain one aggregate manifest without inventing a test-selection policy.

A batch is an orchestration boundary over ordinary immutable test runs. Each
selected test still produces its own verified run evidence.

## Workflow

Choose the exact tests and revision explicitly:

```text
test_batch_run(
  project = "demo",
  test_targets = ["cli-smoke", "error-path", "large-input"],
  branch = "main",
  revision_id = "<reviewed-revision>"
)
```

Re-read the aggregate evidence with:

```text
test_batch_get(batch_id = "<batch-id>")
```

The selection contains between 1 and 64 unique test-target names. Caller order
is preserved exactly.

## No implicit selection

`test_batch_run` does not:

- discover every test automatically;
- expand tags or naming patterns;
- rank, prioritize, shard, or reorder tests;
- infer which tests are relevant to a change;
- imply anything about tests that were not selected.

Selection policy is deliberately separate from execution evidence. An agent,
human, or later policy service must supply the exact bounded list.

## Exact revision capture

The service captures one `revision_id` and resolves every selected test
definition from that same immutable revision before any executable starts.

This guarantees that:

- every `definition_hash` belongs to one coherent project state;
- a missing or malformed test rejects the request before any test runs;
- later branch movement cannot change the batch inputs;
- caller order and definition identity are fixed before execution.

The batch does not mutate the project, advance a branch, or create a project
revision.

## Sandbox boundary

The strict sandbox capability is probed before the first test. If the sandbox
cannot establish the declared isolation policy, the entire request fails with
`SANDBOX_UNAVAILABLE` and publishes no batch manifest.

Each selected test then executes through the ordinary `test_run` path. The
sandbox backend may internally cache its successful capability probe, but the
aggregate manifest still records the exact sandbox policy hash and reported
resource-limit capabilities.

The sandbox limitations documented in `sandboxed-test-runs.md` remain
unchanged. A batch does not strengthen them.

## Outcomes

The aggregate status has three values:

- `passed`: every selected test produced behavioral evidence with
  `passed = true`;
- `failed`: at least one selected test produced valid behavioral evidence with
  `passed = false`, and no selected test had an execution-domain error;
- `incomplete`: at least one selected test returned an independent domain error,
  such as `TEST_BUILD_FAILED`.

A behavioral failure is not an infrastructure error. Its individual run remains
valid immutable evidence and is linked from the batch.

Per-test domain errors do not erase successful or failed sibling evidence. They
are retained in caller order with their error code and definition hash. A later
agent can inspect the successful run IDs and repair only the errored test path.

`SANDBOX_UNAVAILABLE` is different: because the required execution boundary is
not available, it rejects the batch as a whole.

## Aggregate evidence

Each batch manifest binds:

- project, branch, and exact `revision_id`;
- the ordered test-target selection;
- every ordered `definition_hash`;
- sandbox backend, version, policy, policy hash, and reported resource limits;
- a deterministic hash of the complete batch input identity;
- selected, passed, failed, and errored counts;
- ordered per-test outcomes;
- individual run IDs and run-manifest hashes when execution produced evidence;
- structured domain errors when no individual run was published.

The aggregate manifest is published under a random 32-character batch ID. It is
written to a staged directory, validated, and then atomically published under an
exclusive lock. Existing batch identities are never overwritten.

## Verification

`test_batch_get` validates the aggregate manifest and then verifies every linked
individual run through the normal retained-run reader. It checks that each linked
run still has the expected:

- manifest hash;
- test-definition hash;
- pass status.

The individual run manifest remains authoritative for executable, compiler,
observed output, and assertion details. The aggregate does not duplicate those
large records.

## Interpretation limits

A batch manifest is evidence only for the selected tests, exact revision,
selected definitions, retained executables, and recorded sandbox policy.

It is not:

- a project revision;
- a merge preflight or publication permission;
- proof that unselected tests pass;
- proof that the same tests pass at another revision;
- a priority, urgency, or quality signal derived from caller order;
- a replacement for individual run evidence;
- a test-discovery or impact-analysis policy.
