# Reproducible branch creation

## Purpose

Parallel agents need to know exactly which immutable program state they forked.
Creating a branch by reading a source head and inserting the new branch later can
select a different state than the caller reviewed if the source advances during
the operation.

Jacquard provides two explicit branch-creation modes:

- current-head creation with optional optimistic concurrency;
- exact-revision creation for reproducible historical forks.

Neither mode creates a new program revision. A branch points directly at an
existing immutable project revision.

## Current-head branch creation

```text
branch_create(
  project,
  branch,
  from_branch = "main",
  expected_revision_id = optional)
```

The existing tool name, positional arguments, and successful result remain
compatible. The result is the revision ID assigned to the new branch.

The workspace:

1. validates `expected_revision_id` when supplied;
2. captures the current head of `from_branch`;
3. rejects a mismatching prepared expectation;
4. opens `BEGIN IMMEDIATE`;
5. re-reads the source branch head inside the transaction;
6. inserts the new branch only when the source still points at the captured head.

A prepared or mid-call mismatch returns `STALE_BRANCH_HEAD` and inserts no target
branch. Calls without an expectation remain race-safe and return the exact source
head selected by the transaction.

## Exact historical branch creation

```text
branch_create_at_revision(project, branch, revision_id)
```

This tool does not depend on a current source branch. It verifies that the
selected immutable revision belongs to `project`, then inserts the new branch
pointing exactly at that revision.

Use it when:

- resuming work from a recorded revision;
- reproducing an earlier experiment;
- creating an alternative product or implementation from one known base;
- comparing two future developments from a shared historical state;
- a source branch has advanced since the desired fork point.

The selected revision does not need to remain reachable from another current
branch. It must exist and belong to the project.

## Errors

- `INVALID_EXPECTED_REVISION_ID`: malformed current-head expectation;
- `STALE_BRANCH_HEAD`: the reviewed source branch advanced;
- `INVALID_REVISION_ID`: malformed exact revision ID;
- revision not found/project ownership failure: exact revision is unavailable to
  the selected project;
- `DUPLICATE_BRANCH`: the target branch name already exists.

All failures leave existing branch heads and the branch set unchanged.

## State separation

Branches share immutable revisions at the fork point. Later writes publish new
revisions and advance only the selected branch. Stable node IDs inherited from
the fork remain comparable by merge and revision-diff tools.

An exact historical fork may intentionally omit later forms or values present on
the current main branch. `program_render`, `node_find`, `node_inspect`, targets,
context, policy, and builds then resolve from the forked branch head as usual.

## Compatibility

This feature does not change:

- branch table schema;
- revision or snapshot formats;
- stable node IDs;
- merge ancestry or common-base logic;
- compiler protocols, builds, or artifacts;
- the successful `branch_create` result type;
- existing `branch_create` required and positional arguments.

`branch_create_at_revision` is additive.

## Qualification

Direct tests prove:

- prepared current-head creation returns and stores the reviewed revision;
- stale prepared creation inserts no branch;
- a forced source-head advance through a second SQLite connection is rejected;
- exact creation reproduces historical state after main advances;
- foreign-project and malformed revisions are rejected;
- both modes return structured duplicate-name errors.

The production stdio lifecycle proves:

- `branch_create` exposes `expected_revision_id`;
- `branch_create_at_revision` exposes `revision_id`;
- current-head, historical, and unprepared forks receive exact expected heads;
- stale and duplicate attempts do not appear in `branch_list`;
- rendering demonstrates that the historical fork excludes later main-branch
  structure.

Standard CI retains `reproducible-branch-create-trace.json`. The packaged
compiler workflow verifies that the final branch registration does not regress
build, merge, policy, preflight, or artifact behavior.
