# Revisioned task contracts

## Purpose

Task contracts let autonomous coding agents work under reproducible, enforceable
whole-document constraints. A contract is immutable structural project metadata
stored under `@task/<name>` and published in ordinary branch history.

A contract binds:

- one project and branch;
- the exact branch head that existed before the contract was published;
- one owner identity;
- an objective;
- one or more allowed compiler-source documents;
- dependency task names;
- required behavioral test names;
- acceptance criteria;
- a revisioned lifecycle status.

The format is `weave-task-contract-v1`.

## Public workflow

```text
task_create
→ task_get or task_list
→ complete dependency tasks
→ task_node_apply_batch
→ inspect immutable revision operations
→ run required validation and tests
→ task_status_set
→ merge preflight and review
```

The task tools are:

- `task_create`: publish one new branch-bound contract;
- `task_get`: reproduce the full contract at a branch head or exact revision;
- `task_list`: return a bounded lexical page of compact summaries;
- `task_status_set`: publish one owner-authorized status transition;
- `task_node_apply_batch`: apply a bounded ordinary structural batch only after
  contract admission succeeds.

`branch_resume_snapshot` includes bounded task summaries and returns exact
`task_get` recovery arguments.

## Creation contract

`task_create` captures the current branch head as `base_revision_id`. Creation is
compare-and-set safe through `expected_revision_id` and advances the selected
branch by one immutable revision.

The contract is rejected when:

- its name, owner, branch, objective, or list values are invalid or unbounded;
- an allowed document is missing or is reserved project metadata;
- a required behavioral test is missing;
- a dependency is missing or refers to the task itself;
- the branch has advanced from the expected revision;
- a contract with the same name already exists in the selected state.

Allowed documents must be compiler sources. Build-target, test-target, and task
metadata can never be placed in task edit scope.

## Dependency integrity

Every exact state containing task contracts is validated as a graph:

- every named dependency exists;
- self-dependencies are rejected;
- dependency cycles are rejected;
- required tests and allowed documents still exist.

Metadata-aware merge preview applies the same validation to the prospective
merged state. A structurally clean merge is therefore still rejected when it
would publish dangling or cyclic task contracts.

Task-bound editing additionally requires every dependency to have status
`complete` in the exact state being edited.

## Lifecycle

Supported statuses are:

```text
open
in_progress
blocked
ready_for_review
complete
```

Allowed transitions are intentionally explicit:

```text
open             → in_progress | blocked | complete
in_progress      → blocked | ready_for_review | complete
blocked           → in_progress
ready_for_review  → in_progress | complete
complete          → terminal
```

Only the declared owner may transition status. Status changes preserve the task
root and field identities where possible, publish a new revision, and change the
content-derived contract hash.

A task may execute scoped edits only while `open` or `in_progress`. `blocked`,
`ready_for_review`, and `complete` are non-executable states.

## Scoped structural edits

`task_node_apply_batch` reuses the same bounded operation vocabulary as
`node_apply_batch`. Before applying any operation it pins one exact branch head
and checks:

1. the task exists in that state;
2. the task is bound to the selected branch;
3. `actor` equals the declared owner;
4. the task status is active;
5. the selected document is allowed;
6. every dependency is complete;
7. `expected_revision_id`, when supplied, is current.

Only then are the operations applied in memory, structurally validated, and
published through the same atomic branch-head compare-and-set boundary as an
ordinary batch.

Every immutable operation payload receives a `task_contract` object containing:

- `format = weave-task-audit-v1`;
- task name;
- owner and actor;
- task contract hash;
- latest task-contract revision;
- original task base revision;
- task-contract format.

This makes task attribution reproducible from `revision_operations_page` without
requiring a mutable external task tracker.

## Merge and compiler boundaries

Task metadata is reserved project metadata. It is:

- excluded from canonical compiler source lists;
- excluded from build target sources;
- excluded from resume program-document summaries;
- reported separately as `changed_task_documents` in merge impact;
- validated for cross-document integrity in merge preview and publication.

Jacquard does not interpret task acceptance criteria or required-test names as
proof that those criteria or tests passed. Existing build, test, candidate
qualification, preflight, and attestation evidence remains authoritative for its
own narrow claim.

## Honest enforcement boundary

The first task-contract version enforces whole-document scope only through the
explicit `task_node_apply_batch` path.

It does **not** claim:

- that ordinary node tools are globally disabled;
- that no other agent edited the document;
- symbol-level, function-level, or semantic isolation;
- that acceptance criteria were satisfied;
- that required tests ran or passed;
- merge approval or readiness.

Reviewers should inspect operation history and required evidence separately.
Global task-enforcement policy may be added later as an explicit target-branch
policy; it must not be implied by the existence of a contract.

Symbol-level scopes depend on compiler-owned semantic identities, definitions,
and references. That compiler contract is tracked in `weavec` issue #37 rather
than reimplemented in Jacquard.

## Determinism and bounds

- Contract hashes derive from normalized contract content.
- Task list pages use lexical task-name order from one immutable revision.
- Page identities bind the selected revision, limits, summaries, and continuation.
- Task list pages contain counts and hashes, not full objectives or acceptance
  text; use `task_get` for exact content.
- Contract strings and lists have explicit size and cardinality bounds.
- Task-bound batches retain the ordinary maximum of 256 operations.

## Failure semantics

Contract validation, owner, branch, dependency, scope, stale-head, operation, or
structural failures publish no revision and no task-attributed operation rows.
A successful task status transition or task-bound batch creates exactly one new
immutable revision.
