# Branch-write concurrency audit

## Purpose

This audit records which Jacquard branch-mutating paths publish from one captured
base revision and which paths still need strengthening.

## Already compare-and-set safe

- all six single-node structural mutations;
- `node_apply_batch`;
- branch merge preview/preflight publication;
- compiler-gated merge publication.

These paths capture one or more reviewed branch heads and recheck them inside the
same SQLite transaction that publishes the revision.

## Direct state mutations suitable for the existing primitive

The following paths load branch state and then call `_commit` without an expected
head:

- `program_create`;
- `program_import`;
- `build_target_set`;
- `build_target_delete`.

They can be hardened without a schema or storage-format change by:

1. accepting optional `expected_revision_id`;
2. loading state through `_state_for_write`;
3. publishing with `expected_branch_heads={branch: base_revision_id}`;
4. returning `base_revision_id` on success.

## Context-document mutations requiring a separate design

The following paths insert or reuse a `documents` row in one transaction and only
later publish the revision that references it:

- `context_add`;
- `merge_policy_set`.

Adding only a branch compare-and-set would prevent branch clobbering but could
still leave an unreferenced document row when publication loses a race. They need
an atomic document-plus-revision publication primitive or an equivalent
transactional callback inside `_commit`.

## Non-goals

This audit does not classify read-only tools, native builds pinned to immutable
revisions, or branch creation from an explicitly selected source head as stale
state overwrites.
