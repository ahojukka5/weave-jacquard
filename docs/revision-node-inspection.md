# Revision-pinned node inspection

Stable node IDs make it possible to inspect the exact program state that produced
an older build or diagnostic, even after the selected branch has advanced.

## Tool contract

```text
node_inspect(
  project,
  branch,
  document,
  node_id,
  depth = 3,
  revision_id = optional exact revision
)
```

When `revision_id` is omitted, `node_inspect` reads the current head of `branch`.
This preserves the original tool behavior.

When `revision_id` is supplied, Jacquard reads that immutable revision instead.
The revision must belong to `project`. It does not need to be the current branch
head or first-parent reachable from the selected branch. This allows inspection
of older branch states and revisions produced on another project branch.

The selected branch must still exist because the response compares the explicit
revision with its current head.

## Response identity

Every successful response includes:

```text
project
branch
document
branch_head_revision_id
revision_id
revision_is_branch_head
node_id
kind
head
parent_id
position
subtree
annotated_weave
grammar_hint
```

`revision_id` identifies the immutable state actually inspected.
`branch_head_revision_id` identifies the selected branch head at read time.
`revision_is_branch_head` is true only when they are equal.

The node, parent, position, subtree, annotated rendering, and grammar hint are all
derived from `revision_id`, not from the current branch state.

## Diagnostic repair workflow

A failed build is pinned to one immutable revision. The safe repair flow is:

```text
program_build / build_target_build
→ build_diagnostics_page
→ read revision_id and mapped node_id
→ node_inspect(revision_id = failed revision_id, node_id = mapped node_id)
→ inspect the exact failing subtree
→ apply a structural repair at the current branch head
→ program_validate / build_target_validate
→ build again
```

Passing the failed revision matters when another edit, merge, or repair has
already advanced the branch. Without the explicit revision, ordinary inspection
would describe the new head rather than the state that generated the diagnostic.

## Immutability and safety

Historical inspection is read-only:

- it never advances a branch;
- it never checks out or rewrites a revision;
- it does not require the compiler or retained build artifacts;
- it rejects revisions belonging to another project;
- it reports a missing node when that stable ID did not exist in the selected
  revision or had already been deleted there.

A stable ID may identify different values or locations across revisions because
editing and moving preserve identity. The explicit revision therefore remains
part of the meaning of every historical inspection result.
