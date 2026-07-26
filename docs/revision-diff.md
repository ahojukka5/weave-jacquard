# Stable-node revision diffs

## Purpose

`revision_diff_page` compares one program document across two immutable revisions
without rendering or transferring both complete trees. It is intended for agent
review, compiler-guided repair, and branch analysis after the current head has
advanced beyond an earlier build.

The comparison uses stable `n_*` node identities. It does not compute a textual
line diff and does not infer correspondence between unrelated replacement trees.

## Request

```text
revision_diff_page(
  project,
  document,
  base_revision_id,
  branch = "main",
  target_revision_id = optional,
  start_index = 0,
  limit = 50,
)
```

Both explicit revisions must belong to `project`. They do not need to be
ancestor-related or reachable from `branch`. The selected branch is used to
resolve the current head and as the default target when `target_revision_id` is
omitted.

`start_index` is zero-based. `limit` must be between 1 and 200.

## Node descriptors

Each side of a change contains a compact descriptor:

```json
{
  "node_id": "n_example",
  "kind": "integer",
  "head": null,
  "value": 2,
  "parent_id": "n_parent",
  "position": 2,
  "child_count": 0
}
```

Descriptors do not contain complete subtrees or unbounded child-ID arrays. Use
`node_inspect` with the relevant revision when a local subtree is needed.

## Change kinds

One stable node produces at most one row. Its `change_kinds` may contain:

- `added`: the ID exists only in the target revision;
- `removed`: the ID exists only in the base revision;
- `kind_changed`: the stored node kind differs;
- `head_changed`: a list resolves to a different form head;
- `value_changed`: an atom value differs;
- `parent_changed`: the node belongs to a different parent;
- `position_changed`: its zero-based sibling position differs;
- `child_count_changed`: a list has a different number of children.

An added row has `before: null`. A removed row has `after: null`. Common nodes
retain both descriptors so agents can make exact, local decisions.

Position changes are structural facts, not necessarily explicit move operations.
Inserting a sibling before an existing node changes that node's position and is
therefore reported.

## Ordering and pagination

Rows for common and added nodes follow target-document preorder. Removed nodes
follow afterward in base-document preorder. The two selected revisions are
immutable, so the order and continuation remain stable.

The response includes:

- current branch head;
- exact base and target revisions;
- whether the target is the current branch head;
- document-presence and node-count metadata for both sides;
- total changed-node count;
- aggregate counts for every change kind;
- `has_more` and `next_index`;
- the requested bounded page.

When `has_more` is true, pass `next_index` as the next `start_index` with the same
project, document, revisions, branch, and limit.

## Added and removed documents

If the document exists on only one side, every node is reported as added or
removed. If it is absent from both revisions, the request fails because there is
no document comparison to return.

Replacing a complete imported program normally creates unrelated stable IDs. The
result therefore reports the old tree as removed and the new tree as added rather
than inventing node correspondence.

## Compiler-guided repair

Recommended flow:

```text
program_build / build_target_build
→ build_diagnostics_page
→ node_inspect(revision_id = failed build revision)
→ revision_diff_page(
     base_revision_id = failed build revision,
     target_revision_id omitted
   )
→ repair the current branch through stable-ID structural tools
→ program_validate / build_target_validate
→ build again
```

The diff answers whether the mapped node still exists, has already changed, moved,
or was replaced before an agent applies another repair. It never mutates a branch
or build artifact.
