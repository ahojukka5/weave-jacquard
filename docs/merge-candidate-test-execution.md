# Sandboxed behavioral qualification of virtual merge candidates

Jacquard can explicitly build and run selected behavioral tests against one exact
clean virtual branch-merge candidate without publishing the merge.

This is a separate evidence path from committed-revision builds and test runs. A
virtual candidate has no revision ID, so its manifests use a subject with
`committed_revision_id = null` and bind the exact merge preview instead.

## Workflow

```text
preview = branch_merge_preview(
  project = "demo",
  target_branch = "main",
  source_branch = "feature"
)

plan = branch_merge_test_impact(
  project = "demo",
  target_branch = "main",
  source_branch = "feature",
  preview_id = preview.preview_id
)

qualification = branch_merge_test_batch_run(
  **plan.candidate_execution.arguments
)
```

The execution call always requires:

- project;
- target branch;
- source branch;
- exact non-empty `preview_id`;
- an explicit unique ordered list of 1 to 64 test-target names.

The executor does not discover tests, expand tags, infer affected tests, rank
candidates, or reorder caller input. `branch_merge_test_impact` is an optional
structural planning step; execution remains an explicit caller decision.

## Captured candidate

At request start, Jacquard recreates the current merge preview and rejects:

- an invalid or empty preview ID;
- a preview ID that no longer matches current target and source heads;
- a structurally conflicted merge;
- a clean preview that does not retain its in-memory merged state.

It then captures one exact subject:

```text
kind = virtual_merge_candidate
project = <project>
target_branch = <target>
source_branch = <source>
base_revision_id = <common base>
target_head_revision_id = <target head>
source_head_revision_id = <source head>
preview_id = <preview identity>
merged_root_hash = <candidate state hash>
committed_revision_id = null
```

All selected definitions and build targets are resolved from that one captured
state before execution begins.

## Candidate build artifacts

Each distinct referenced build target is compiled once. Tests sharing a target
reuse the same verified executable.

Candidate builds use `weave-merge-candidate-build-manifest-v1`, not the committed-
revision build format. A content-derived build ID binds:

- the complete virtual-candidate subject;
- build-target name, definition hash, ordered documents, and compiler target;
- rendered source hashes;
- compiler executable hash;
- requested native or explicit compiler target.

Source maps identify `virtual_merge_candidate`, the exact preview ID, merged root
hash, and `committed_revision_id = null`.

On every read, Jacquard reconstructs the candidate from the three immutable
revision states, verifies their common ancestor and deterministic preview ID,
re-runs structural merge validation, and checks the merged root hash. It then
verifies the target definition, source hashes, content-derived build ID, compiler
protocol evidence, and every referenced artifact hash.

Use:

- `branch_merge_build_target` to build one target explicitly;
- `merge_candidate_build_get` to re-read a verified manifest;
- `merge_candidate_build_diagnostics_page` to inspect bounded mapped diagnostics.

Public responses remove server-local artifact paths, build directories, and the
compiler command.

## Sandbox execution

Before the first test, Jacquard probes the same strict sandbox capability used by
committed-revision behavioral tests. If strict isolation is unavailable, the
whole request returns `SANDBOX_UNAVAILABLE`; it never falls back to an
unrestricted host subprocess.

Each selected definition contributes its own:

- command-line arguments;
- standard input;
- expected exit code, stdout, and stderr;
- timeout, memory, output, and file-size limits.

The sandbox capability response remains authoritative. Callers must not infer
seccomp, process-count controls, or other boundaries that the backend does not
report.

## Outcomes and evidence

A behavioral assertion produces immutable `passed` or `failed` evidence. A
candidate build that does not produce an executable creates an independent
`error` result and makes the aggregate qualification `incomplete`.

Aggregate status is:

- `passed` when every selected test passes;
- `failed` when no independent error occurs and at least one behavioral assertion
  fails;
- `incomplete` when one or more selected tests cannot execute because their
  candidate build failed.

The aggregate manifest binds:

- the exact virtual-candidate subject;
- caller-ordered test selection;
- every candidate definition hash and target binding;
- every candidate build ID, build-input hash, manifest hash, and status;
- sandbox policy hash;
- per-test limits, executable hash, expected and observed hashes, assertions, and
  outcomes;
- exact counts and aggregate status;
- retained output artifact hashes.

Use `merge_candidate_test_batch_get` to re-read and verify the complete graph.
Use `merge_candidate_test_output_page` for bounded, binary-safe stdout or stderr
inspection.

Existing evidence remains valid even if branch heads later move because it is
reconstructed from immutable revision IDs. The manifest also records whether the
target and source heads were still current when execution completed.

## Publication boundary

Candidate qualification:

- creates no project revision;
- advances no branch;
- publishes no merge;
- does not call merge preflight automatically;
- does not make a successful test result a merge credential.

`heads_unchanged_at_completion` and
`publication_candidate_current_at_completion` are recorded observations, not
admission decisions or bearer tokens.

A caller must still invoke `branch_merge` separately with the same preview ID.
That operation recreates the current preview and rejects stale target or source
heads.

## Interpretation limits

Passing selected candidate tests does not prove:

- complete semantic test coverage;
- correctness of unselected behavior;
- compiler-backed merge-preflight admission;
- target-policy compliance;
- human approval or production readiness;
- that a later changed branch still has the same candidate.

A failed behavioral assertion is useful retained evidence, not a sandbox failure.
A build error is verified compiler evidence, not proof that sibling targets or
tests are invalid.
