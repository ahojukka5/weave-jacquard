# Revisioned behavioral test targets

Jacquard stores behavioral expectations as immutable structural metadata beside
programs and named build targets. A test definition describes how a future
sandbox runner must execute one exact build target. It does not execute the
program and does not claim that the test passed.

## Workflow

Create the program and its named build target first, then publish the test from
the exact reviewed branch head:

```text
program_create(...)
build_target_set(...)
test_target_set(
  project = "demo",
  branch = "main",
  name = "cli-smoke",
  build_target = "application",
  arguments = ["--count", "3"],
  stdin = "input\n",
  expected_exit_code = 0,
  expected_stdout = "done\n",
  expected_stderr = "",
  timeout_ms = 2000,
  max_memory_bytes = 33554432,
  max_output_bytes = 8192,
  max_file_bytes = 4096,
  tags = ["smoke", "cli/fast"],
  expected_revision_id = "<reviewed-head>"
)
```

A successful response identifies both the consumed base and published revision:

```json
{
  "ok": true,
  "result": {
    "name": "cli-smoke",
    "build_target": "application",
    "arguments": ["--count", "3"],
    "expected_exit_code": 0,
    "timeout_ms": 2000,
    "network_policy": "deny",
    "filesystem_policy": "isolated",
    "base_revision_id": "<reviewed-head>",
    "revision_id": "<new-revision>",
    "storage_document": "@test-target/cli-smoke",
    "root_node_id": "n_...",
    "definition_hash": "..."
  }
}
```

`definition_hash` is the deterministic hash of the exact structural definition.
`test_target_get` returns the complete definition and the same hash at an exact
revision.

Use `test_target_list` for bounded lexical discovery. It accepts `revision_id`,
`start_after_name`, and `limit`, and returns:

- total and returned test counts;
- `test_targets_truncated`;
- exact `next_after_name` continuation;
- bounded summaries with expectation byte counts and `definition_hash`;
- an exact `test_target_get` call for each full definition.

Large stdin/stdout/stderr bodies never appear in list pages. Omit `revision_id`
only when the current branch head is intentionally desired.
`test_target_delete` creates another immutable revision and supports
`expected_revision_id`.

## Definition contract

Each test binds to an existing named build target and records:

- ordered command-line arguments;
- controlled standard input;
- exact expected exit code, standard output, and standard error;
- timeout, memory, output, and generated-file limits;
- optional bounded tags;
- `network_policy = "deny"`;
- `filesystem_policy = "isolated"`.

Names, argument counts, tags, text sizes, and resource values are bounded before
publication. Updates preserve the stable root identity when the same test name
is replaced. Stale compare-and-set writes publish no revision or operation.

A referenced build target cannot be deleted until its tests are deleted or
retargeted. Ordinary merge previews, direct merge publication, and ordered
virtual merge trains all validate the combined candidate state. A candidate that
would leave a test bound to a missing build target is rejected before any branch
advances.

## Metadata boundary

Test definitions use reserved structural document names under
`@test-target/`. They participate in immutable revisions, diffs, branches, and
merges, but they are not Weave source code.

Consequently, Jacquard excludes them from:

- `program_source_list`;
- named build-target source validation;
- compiler input construction;
- changed-program and uncovered-program merge calculations;
- the program-document portion of agent resume snapshots.

Merge impact reports test-definition changes separately as
`changed_test_documents`.

## Resume snapshots

`branch_resume_snapshot` accepts `test_target_limit`. It returns bounded test
summaries containing the target binding, expectation sizes, exit status,
resource policy, tags, stable root ID, `definition_hash`, and an exact
`test_target_get` call. Large stdin/stdout/stderr bodies remain behind that
focused read.

The summary is orientation evidence only. It does not contain a run status.

## Execution boundary

This capability deliberately exposes no unrestricted `program_run` operation.
A later runner must:

1. resolve the exact project revision and `definition_hash`;
2. build the referenced target reproducibly;
3. enforce denied networking and isolated filesystem access;
4. enforce every resource and output bound;
5. retain bounded outputs, checksums, termination reason, and resource usage;
6. publish an immutable run identity;
7. compare the observed result with the exact stored expectations.

Until such evidence exists, a test definition means only “this behavior is
required,” never “this behavior was demonstrated.”
