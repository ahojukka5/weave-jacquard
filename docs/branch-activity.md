# Branch activity observability

Long-lived agent branches can contain hundreds or thousands of immutable
revisions, and one grouped revision may contain hundreds of ordered operation
rows. Jacquard exposes three read-only tools for bounded review:

- `branch_history_page`
- `revision_operations_page`
- `branch_activity_summary`

The existing `branch_history` tool remains available and now returns the same
bounded truncation evidence as the compatibility history page path, while
`branch_history_page` stays the continuation-oriented paging tool. None of the
observability tools changes revisions, branches, operation rows, or the database
schema.

## Paginated first-parent history

```text
branch_history_page(
  project,
  branch = "main",
  start_revision_id = null,
  limit = 50
)
```

`limit` must be between 1 and 200. The first call normally omits
`start_revision_id`, so reading begins at the current branch head.

The response contains:

```text
project
branch
branch_head_revision_id
start_revision_id
limit
returned_count
has_more
next_revision_id
revisions
```

Each revision includes its parents, message, author, root hash, timestamp,
relative page depth, operation count, and operation kinds in original sequence
order.

When `has_more` is true, call the tool again with
`start_revision_id=next_revision_id`. That revision is included as the first item
of the next page, so no revision is skipped or duplicated between pages.

A supplied start revision must be reachable from the selected branch head by
following first parents. A revision from another branch is rejected with
`REVISION_NOT_REACHABLE` rather than silently changing the history being read.

The branch head is returned on every page. A caller that requires a stable
multi-page snapshot can compare it with the first page and restart if the branch
advanced between calls.

## Paginated revision operation audit

```text
revision_operations_page(
  project,
  revision_id,
  start_sequence_number = 0,
  limit = 50
)
```

Operation pages are project-scoped and immutable. The revision must belong to the
named project. `start_sequence_number` must be a non-negative integer, and
`limit` must be between 1 and 200.

The response contains revision metadata, total operation count, page bounds,
continuation fields, and ordered operation rows:

```text
revision
start_sequence_number
limit
total_operation_count
returned_count
has_more
next_sequence_number
operations
```

Each operation contains:

```text
id
sequence_number
operation_kind
target
payload
```

`payload` is the exact stored JSON object. For a transactional edit it includes
`batch_index`, so reviewers can compare the public audit page with the original
ordered batch. Targets and payloads are returned without rewriting stable node
IDs.

When `has_more` is true, call the tool again with
`start_sequence_number=next_sequence_number`. The next sequence is included as
the first operation on the next page. Unlike branch history, no branch-head
stability check is needed while paging one revision because revisions and their
operation rows are immutable.

A revision with no operation rows returns an empty page with
`total_operation_count=0` and `has_more=false`.

## Activity summary

```text
branch_activity_summary(project, branch = "main")
```

The summary traverses the complete first-parent history and returns:

- revision and first-parent edge counts;
- merge revision count;
- total operation count;
- zero-, single-, and multi-operation revision counts;
- mutation revision count;
- maximum operations in one revision;
- average operations per mutation revision;
- operation-kind totals;
- revision counts by author;
- oldest and newest revision identities and timestamps;
- `revision_count_avoided_by_grouping`.

`revision_count_avoided_by_grouping` is:

```text
sum(max(0, operation_count_in_revision - 1))
```

It measures how many additional revisions the same recorded operations would
have required under a strict one-operation-per-revision model. It does not claim
to measure token cost, wall-clock latency, or semantic complexity.

## Example

A project containing initialization, one `program_create`, and one nine-operation
structural transaction reports:

```text
revision_count                       3
operation_count                     10
zero_operation_revision_count       1
single_operation_revision_count     1
multi_operation_revision_count      1
max_operations_per_revision         9
average_operations_per_mutation     5.0
revision_count_avoided_by_grouping   8
```

The branch history pages as two revisions followed by one revision. The grouped
revision's nine audit rows page as four, four, and one operation using the
returned sequence continuation.

## Operational intent

Use `branch_history_page` when reviewing exact revision order. Use
`revision_operations_page` when reviewing the target and payload of every edit
inside one revision. Use `branch_activity_summary` when comparing agent
workflows, evaluating transaction grouping, or checking whether a branch is
accumulating excessive revisions.

These metrics are descriptive. They should guide further ergonomics work, not
automatically reward large batches. A low revision count is not useful if it
hides uncertain edits, weak validation, or poor auditability.
