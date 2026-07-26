# Branch-write concurrency audit

## Purpose

This audit records the publication boundary for every known Jacquard MCP path
that advances an existing branch head.

## Compare-and-set safe

- `program_create`;
- `program_import`;
- all six single-node structural mutations;
- `node_apply_batch`;
- `build_target_set`;
- `build_target_delete`;
- `context_add`;
- `merge_policy_set`;
- branch merge preview/preflight publication;
- compiler-gated merge publication.

These paths capture one or more reviewed branch heads and recheck them inside the
same SQLite transaction that publishes the revision. Program, node, batch,
target, context, and policy writes accept optional `expected_revision_id` where
one target branch is mutated; successful direct writes report
`base_revision_id`.

Context and policy publication use the stronger content-document invariant: the
content-addressed `documents` row, dynamic operation payload, inherited and new
revision-document links, immutable revision, and conditional branch update all
commit or roll back together.

## Other writes

Project initialization creates the project, initial revision, and main branch as
one database operation. Branch creation copies one current source head while
inserting a new branch row; it does not overwrite an existing branch. Explicit
checkout intentionally moves a branch to a caller-selected project revision and
is not a prepared state transformation.

Native builds and validations are pinned reads of immutable revisions and do not
advance branches. Read-only tools do not participate in this audit.

## Ongoing rule

Any new existing-branch mutation must document and test:

1. the exact branch state read;
2. optional prepared-state expectation semantics;
3. the transaction that publishes all persistent consequences;
4. the conditional branch-head update;
5. rollback evidence for stale or mid-publication failure;
6. response provenance identifying the selected base.

A write that creates auxiliary persistent rows must publish those rows and their
revision references in the same transaction. Preventing branch clobbering alone
is insufficient when a failed attempt could leave orphan state.
