# Atomic context and merge-policy publication

## Purpose

Jacquard context and merge policies are stored as content-addressed rows in the
`documents` table and linked to immutable revisions through
`revision_documents`. Publishing the document in one transaction and the
referencing revision in another creates two failure modes:

- a concurrent branch advance can overwrite newer work;
- a lost race or later publication failure can leave an orphan document row.

`context_add` and `merge_policy_set` therefore publish the complete document and
revision graph atomically.

## Public tools

Both tools preserve their existing arguments and add:

```text
expected_revision_id = optional non-empty branch-head revision
```

Every successful response adds:

```text
base_revision_id = exact immutable revision used as parent1
```

Prepared agents should pass the revision from which the context or policy was
planned. Calls that omit the expectation remain compare-and-set safe and report
their captured base afterward.

## Transaction preparation hook

`RevisionWorkspace._commit` accepts an internal `prepare_transaction` callback.
The callback runs only after all expected branch heads have been checked inside
`BEGIN IMMEDIATE` and before the revision row is inserted.

It returns:

```text
(dynamic operations, dynamic document IDs)
```

The normal commit path then publishes:

1. the immutable revision row;
2. all module snapshots;
3. static and dynamically prepared operation rows in sequence order;
4. inherited, static, and dynamically prepared document links;
5. the conditional branch-head update.

Any callback, SQL, validation, or branch-update failure rolls back every item.
Existing callers that do not provide a callback retain their original operation
and document-link behavior.

Inherited document IDs are resolved inside the same transaction. This keeps the
selected parent revision, its context set, dynamic documents, and the new
revision on one atomic database snapshot.

## Content-addressed document preparation

The public `SExpressionWorkspace` provides one shared internal publisher for
context and policy documents. It hashes the canonical envelope:

```json
{
  "scope_kind": "...",
  "scope_name": "...",
  "title": "...",
  "body": "..."
}
```

Inside the revision transaction it:

- reuses the row with the same unique `content_hash`, or inserts a new UUID row;
- adds the actual `document_id` to the operation payload;
- returns that ID as a revision-document link;
- lets the normal commit path publish the revision and conditional branch update.

An identical context or policy body reuses one document row while each new
revision still receives its own immutable link and audit operation.

## Context publication

`context_add` keeps the existing scopes:

- `project`;
- `document`;
- `symbol`.

It preserves `add_context`, the requested scope target, existing context lookup,
and the historical content-hash definition. A stale prepared request returns
`STALE_BRANCH_HEAD` before inserting or reusing any row for the attempted write.

## Merge-policy publication

`merge_policy_set` continues to:

- normalize and validate the same `weave-merge-policy-v1` object;
- store canonical JSON under the same project scope and title;
- record `set_merge_policy` with policy format, hash, and document ID;
- resolve policy through first-parent operation history;
- make the target branch policy authoritative for preflight and publication.

The final MCP registration replaces only the policy setter. Policy reads,
preflight composition, branch merge enforcement, historical policy resolution,
and source-policy visibility all use the same race-safe registry cache.

## Failures and rollback

- `INVALID_EXPECTED_REVISION_ID`: malformed expectation;
- `STALE_BRANCH_HEAD`: expected or captured branch head is no longer current;
- existing scope and merge-policy validation errors remain unchanged.

On failure, the following must remain unchanged:

- branch head;
- revision and snapshot counts;
- operation rows;
- document rows;
- revision-document links.

There must be no document row lacking at least one immutable revision link as a
result of these write paths.

## Compatibility

This feature does not change:

- database schema or schema version;
- content hashes or document IDs already stored;
- revision, operation, or context-document formats;
- merge-policy format, hash, operation kind, title, or first-parent resolution;
- compiler protocols, build keys, manifests, or Weave language behavior;
- public tool names or existing positional arguments.

The transaction preparation hook is internal and optional. It introduces no new
stored protocol identifier.

## Qualification

Direct tests prove:

- atomic context document, link, operation, revision, and branch publication;
- identical-content document reuse;
- stale context and policy rejection with no new rows;
- rollback of a document inserted by a preparation callback that later raises;
- unchanged policy resolution, policy hash, operation kind, and document link.

The production stdio lifecycle proves:

- both public schemas expose `expected_revision_id`;
- prepared and unprepared context/policy writes report exact bases;
- identical context is reused;
- stale writes leave the branch unchanged;
- policy reads resolve the newly published policy;
- no stale-title or unreferenced document remains after the server exits;
- every retained context/policy operation refers to a linked document.

Standard CI retains `context-policy-concurrency-trace.json`. The packaged
`weavec` matrix verifies that atomic policy publication does not regress policy
enforcement, preflight, merge publication, native builds, or artifact discovery.
