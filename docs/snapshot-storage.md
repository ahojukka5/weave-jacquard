# Immutable snapshot storage

Every accepted mutation still creates one immutable revision. The workspace SQL
contract remains `module_snapshots(revision_id, qualified_name, ast_json,
ast_hash)`, so history, checkout, merge, rendering, validation, and build code do
not need storage-specific branches.

## Physical layout

Canonical AST JSON is stored in `module_snapshots_compressed.ast_blob`. The
public `module_snapshots` object is a SQLite view that decodes the payload, with
`INSTEAD OF` triggers preserving the existing insert, update, and delete
contract.

Each payload begins with a four-byte format marker:

- `WJZ1`: zlib-compressed UTF-8 canonical JSON;
- `WJR1`: raw UTF-8 canonical JSON when compression would be larger.

Compression uses zlib level 3. This keeps mutation overhead low while reducing
the repeated full-snapshot payload substantially. The backing table remains
inspectable with ordinary SQLite tools even though reading the decoded logical
view requires the application connection that registers the decoder function.

## Existing database migration

Opening a database with the legacy physical `module_snapshots.ast_json` table
performs one transactional migration:

1. acquire an immediate write transaction;
2. rename the legacy table;
3. create the compressed backing table;
4. encode and copy every historical snapshot;
5. create the logical view and its DML triggers;
6. remove the legacy table and commit;
7. run `VACUUM` once to reclaim uncompressed pages.

If migration fails, the transaction is rolled back. Branch heads, revision IDs,
root hashes, operation logs, context documents, AST hashes, and canonical JSON
content are unchanged.

Because migration rewrites and vacuums the database, normal operational backup
rules still apply: keep a consistent backup before opening an important legacy
database with a newer frontend release, and do not run concurrent writers during
the first migration startup.

## Scope and future work

This change compresses full immutable snapshots; it does not alter their
semantics or introduce delta reconstruction. A content-addressed immutable node
store could reduce repeated subtrees further, but it would change the persistence
model and should be evaluated separately after production experience with the
transparent compression layer.
