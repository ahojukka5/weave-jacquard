# Immutable snapshot storage

Every accepted mutation creates one immutable revision. The logical workspace SQL
contract remains:

```text
module_snapshots(revision_id, qualified_name, ast_json, ast_hash)
```

The physical store is compressed, but every production revision read now bypasses
implicit trust in that view and verifies the backing evidence directly.

## Physical layout

Canonical AST JSON is stored in `module_snapshots_compressed.ast_blob`. The
`module_snapshots` object is a SQLite view that decodes the payload, with
`INSTEAD OF` triggers preserving the historical insert, update, and delete SQL
contract.

Each payload begins with a four-byte format marker:

- `WJZ1`: zlib-compressed UTF-8 JSON;
- `WJR1`: raw UTF-8 JSON when compression would be larger.

Compression uses zlib level 3.

## Shared bounded codec

The SQLite view, production workspace, database integrity checker, legacy migration
admission, online backup verification, and offline restore verification all use one
snapshot codec.

The codec enforces:

- at most 16 MiB in one encoded blob;
- at most 32 MiB of decoded UTF-8 bytes;
- incremental zlib decompression with a hard output ceiling;
- complete zlib end markers;
- no trailing compressed bytes;
- a recognized four-byte prefix;
- valid UTF-8 and JSON;
- a JSON-object root;
- production S-expression structural limits;
- canonical-state SHA-256 equality with the stored `ast_hash`.

The codec never calls unbounded `zlib.decompress` on retained database data.

## Revision reconstruction

A revision read selects the compressed rows directly in lexical qualified-name
order. It admits at most 4,096 modules and 256 MiB of aggregate decoded snapshot
bytes. Qualified names are non-empty, NUL-free, and at most 4,096 UTF-8 bytes.

After every module passes structural and `ast_hash` verification, Jacquard hashes
the complete canonical module mapping and compares it with the stored revision
`root_hash`. A failure is returned as `CORRUPT_REVISION_STATE`; the partial state is
never returned to callers.

These checks protect rendering, structural editing, merge analysis, compiler input
materialization, testing, evidence inspection, and agent reads because all of those
production paths begin from the verified workspace state loader.

## Existing database migration

Opening a database with the legacy physical `module_snapshots.ast_json` table first
runs read-only semantic admission over every legacy row and revision. Only after
legacy JSON, structural trees, AST hashes, revision roots, operations, context
hashes, and parent history pass does the transactional migration begin:

1. acquire an immediate write transaction;
2. rename the legacy table;
3. create the compressed backing table;
4. bounded-encode and copy every historical snapshot;
5. create the logical view and its DML triggers;
6. remove the legacy table and commit;
7. run `VACUUM` once to reclaim uncompressed pages;
8. install the complete current schema.

If admission or migration fails, the original schema version and data remain
unchanged.

## Persistence model

This design still stores complete immutable module snapshots rather than deltas. It
does not introduce subtree deduplication or content-addressed node storage. Such a
change would alter persistence, backup, and reconstruction semantics and should be
considered only after measured storage evidence justifies it.
