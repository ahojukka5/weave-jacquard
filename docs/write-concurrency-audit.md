# Branch-write concurrency audit

## Purpose

This audit records which Jacquard branch-mutating paths publish from one captured
base revision and which paths still need strengthening.

## Compare-and-set safe

- `program_create`;
- `program_import`;
- all six single-node structural mutations;
- `node_apply_batch`;
- `build_target_set`;
- `build_target_delete`;
- branch merge preview/preflight publication;
- compiler-gated merge publication.

These paths capture one or more reviewed branch heads and recheck them inside the
same SQLite transaction that publishes the revision. Program, node, batch, and
target writes accept optional `expected_revision_id`; successful direct writes
report `base_revision_id`.

## Context-document mutations requiring a separate design

The following paths insert or reuse a `documents` row in one transaction and only
later publish the revision that references it:

- `context_add`;
- `merge_policy_set`.

Adding only a branch compare-and-set would prevent branch clobbering but could
still leave an unreferenced document row when publication loses a race. They need
an atomic document-plus-revision publication primitive or an equivalent
transactional callback inside `_commit`.

The required invariant is stronger than branch safety:

- the context document row must be inserted or reused;
- its revision link and operation audit row must be published;
- the branch head must be conditionally advanced;
- every part must commit or roll back as one SQLite transaction.

## Non-goals

This audit does not classify read-only tools, native builds pinned to immutable
revisions, or branch creation from an explicitly selected source head as stale
state overwrites.
