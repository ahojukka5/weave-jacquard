# Optimistic concurrency for single-node writes

## Purpose

Jacquard agents often inspect one immutable branch state, decide on a small
structural repair, and then call one of the six single-node mutation tools. A
second writer may advance the branch between inspection and publication.

Single-node writes therefore use the same branch-head compare-and-set principle
as bounded batches and merge publication. A stale writer must never overwrite a
newer revision.

## Covered tools

The contract applies to:

- `node_create_form`;
- `node_add_atom`;
- `node_set_atom`;
- `node_delete`;
- `node_move`;
- `node_wrap`.

Every tool keeps its existing required and positional arguments. Each adds one
optional request field:

```text
expected_revision_id = optional immutable branch-head revision
```

Every successful response adds:

```text
base_revision_id = exact branch revision read and mutated
```

Existing callers may omit the request field and ignore the additional response
field.

## Prepared writes

An agent that inspected or rendered a particular branch head should pass that
revision as `expected_revision_id`:

```text
node_inspect(...)
→ remember revision_id
→ node_set_atom(..., expected_revision_id = revision_id)
```

The workspace validates that the supplied value is a non-empty string and
compares it with the current branch head before loading mutable working state.
A mismatch returns:

```json
{
  "code": "STALE_BRANCH_HEAD",
  "message": "branch 'main' advanced from 'old' to 'new'",
  "node_id": null
}
```

An empty or non-string value returns `INVALID_EXPECTED_REVISION_ID`.

No revision, snapshot, operation row, or branch update is published on either
failure.

## Unprepared writes

Omitting `expected_revision_id` does not disable concurrency protection.
Jacquard:

1. reads and captures the current branch head;
2. loads program state from that exact immutable revision;
3. applies and structurally validates the requested node mutation;
4. opens the publication transaction;
5. verifies that the branch still points to the captured head;
6. publishes the new revision with a conditional branch-head update.

If another writer advances the branch between steps 1 and 5, publication returns
`STALE_BRANCH_HEAD` and rolls back completely.

The caller cannot predeclare which revision an unprepared write will use, so it
should inspect the returned `base_revision_id` when provenance matters.

## Atomic publication

The new revision uses `base_revision_id` as `parent1_id`. The immutable snapshot,
ordered operation row, inherited context-document links, and conditional branch
update are written in one SQLite transaction.

The branch update is equivalent to:

```sql
UPDATE branches
SET head_revision_id = :new_revision
WHERE project_id = :project
  AND name = :branch
  AND head_revision_id = :base_revision;
```

A row count other than one is a stale write and causes the transaction to roll
back.

## Stable-node behavior

Concurrency protection does not alter structural semantics:

- editing an atom preserves its stable node ID;
- moving a node preserves its stable node ID;
- wrapping creates one new wrapper ID and preserves the wrapped node ID;
- creating forms and atoms returns new IDs;
- deleting removes the selected subtree;
- grammar hints, annotated rendering, position rules, and operation kinds remain
  unchanged.

`base_revision_id` identifies the state from which these consequences were
computed. `revision_id` identifies the newly published state.

## Interaction with batches

Use single-node tools while exploring, repairing, or making one uncertain local
change. Use `node_apply_batch` when a complete coherent local structure is
already known.

Both paths accept `expected_revision_id` and reject stale prepared state. Their
publication units differ:

- a single-node call publishes one ordinary operation in one revision;
- a batch publishes multiple ordered ordinary operations in one revision.

Neither path may silently rebase or replay a stale request on a newer branch
head.

## MCP registration

The production `weave-mcp` entry point replaces the historical six node-tool
registrations with race-safe functions under the same public names. The shared
workspace factory is configured with the race-safe public
`SExpressionWorkspace` before any MCP service can populate its cache.

This keeps node tools, batches, target services, builds, diagnostics, and merge
services on one SQLite connection and one workspace instance.

## Compatibility

This feature does not change:

- the database schema;
- revision or operation storage formats;
- node ID formats;
- compiler protocols;
- build keys or manifests;
- source rendering or Weave language behavior;
- public tool names or existing positional parameters.

Successful responses are backward-compatible object extensions. Structured
validation errors retain the existing `node_id` field, including `null` for
branch-level failures.

## Qualification

Direct tests cover:

- all six successful mutations and their exact `base_revision_id`;
- stale prepared calls for all six tools;
- empty and non-string expectations;
- a forced mid-call branch advance using two SQLite workspace connections;
- complete rollback and preservation of the concurrent writer's branch head.

The production stdio MCP qualification proves:

- all six public schemas expose `expected_revision_id`;
- every prepared call reports the supplied current base;
- atom edit and move preserve stable IDs;
- stale prepared publication returns `STALE_BRANCH_HEAD`;
- the branch head remains unchanged after rejection;
- an unprepared write still reports and compare-and-sets its captured base.

Standard CI retains `single-node-concurrency-trace.json` together with the
historical-read trace. The packaged `weavec` workflow verifies that replacing the
shared workspace and node registrations does not regress the complete native
build and merge matrix.
