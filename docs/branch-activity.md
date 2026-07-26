# Branch activity observability

Long-lived agent branches can contain hundreds or thousands of immutable
revisions. `branch_history` remains available for compact compatibility reads,
but its `limit` parameter does not provide an explicit continuation contract.

Jacquard therefore exposes two additional read-only tools:

- `branch_history_page`
- `branch_activity_summary`

Neither tool changes revisions, branches, or the database schema.

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

The same history pages as two revisions followed by one revision, using the
returned continuation cursor.

## Operational intent

Use the page tool when reviewing exact revision and operation order. Use the
summary when comparing agent workflows, evaluating transaction grouping, or
checking whether a branch is accumulating excessive revisions.

These metrics are descriptive. They should guide further ergonomics work, not
automatically reward large batches. A low revision count is not useful if it
hides uncertain edits, weak validation, or poor auditability.
