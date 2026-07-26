# Transactional structural edits

`node_apply_batch` groups a coherent set of ordinary stable-ID edits into one
immutable revision. It reduces MCP round trips and revision amplification without
replacing the existing single-node tools.

## When to use it

Use single-node tools when:

- exploring an unfamiliar form;
- repairing one uncertain location;
- inspecting after each small decision;
- responding to a validation diagnostic.

Use `node_apply_batch` when the intended local structure is already known, such
as constructing one function body, one control-flow block, or a generated table
of repetitive forms.

A batch is not a nested AST replacement. It is a bounded, ordered, flat list of
the same operations available individually.

## Request

```text
project                  project name
document                 one program document
branch                   branch to advance, default main
operations               1..256 ordered structural operations
expected_revision_id     optional optimistic-concurrency guard
message                   optional revision message
author                    optional revision author
include_operation_results include compact per-operation results, default false
```

The supported operation names are:

- `create_form`
- `add_atom`
- `set_atom`
- `move_node`
- `wrap_node`
- `delete_node`

Unknown fields and unknown operation names are rejected rather than ignored.
Positions use the same zero-based, append-by-default semantics as the individual
tools.

## Temporary aliases

A created form, atom, or wrapper may define an alias with the `as` field. Later
operations in the same batch reference it using `@alias`.

```json
{
  "project": "example",
  "document": "main.weave",
  "expected_revision_id": "previous-revision-id",
  "message": "construct main entry",
  "operations": [
    {
      "op": "create_form",
      "parent": "n_program_root",
      "head": "entry",
      "as": "entry"
    },
    {
      "op": "add_atom",
      "parent": "@entry",
      "kind": "symbol",
      "value": "main"
    },
    {
      "op": "create_form",
      "parent": "@entry",
      "head": "params"
    },
    {
      "op": "create_form",
      "parent": "@entry",
      "head": "returns",
      "as": "returns"
    },
    {
      "op": "add_atom",
      "parent": "@returns",
      "kind": "symbol",
      "value": "i32"
    }
  ]
}
```

Aliases exist only during that batch. The response maps surviving aliases to
stable `n_*` node IDs. Use those returned IDs in later batches.

## Publication and rollback

The executor:

1. pins the current branch head;
2. optionally verifies `expected_revision_id`;
3. loads the exact pinned document state;
4. applies every operation in memory;
5. performs one full structural validation;
6. opens an immediate SQLite transaction;
7. verifies that the branch still points to the pinned revision;
8. writes one immutable snapshot and every ordered operation-log row;
9. advances the branch with a compare-and-set update.

If any operation, alias, position, reference, final validation, or branch-head
check fails, the complete batch is rejected. The branch head, snapshots, and
operation log remain unchanged.

Each sub-operation remains auditable. One revision may therefore contain many
`operations` rows with consecutive sequence numbers and a `batch_index` in each
payload.

## Response

The default response remains compact:

```text
revision_id
base_revision_id
branch
document
root_node_id
operation_count
created_node_count
deleted_node_count
node_count
aliases
```

`created_node_count` counts explicit operation targets. `node_count` counts the
complete stored tree, including the stable head-symbol atom automatically owned
by every form.

Set `include_operation_results=true` when the caller needs the position and node
result for every sub-operation. Avoid enabling it for large generated batches
unless that detail is useful.

## Qualification target

The real-MCP qualification constructs a balanced sum of 80 constants:

- 246 explicit structural operations and edit targets;
- 418 stored nodes after including each form's stable head-symbol atom;
- one `node_apply_batch` write call instead of 246 atomic write calls;
- three reachable revisions in total instead of the 248-revision atomic
  equivalent;
- authoritative `weavec` validation and native build;
- WIR, LLVM, and bitcode regeneration;
- native exit status 80.

The test records elapsed batch time and exact artifact sizes as evidence, but it
asserts correctness and reduction ratios rather than a hardware-dependent timing
threshold.
