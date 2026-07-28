# Verified database backup and restore

Jacquard stores program history, branches, snapshots, operations, context, policy,
task contracts, build definitions, and test definitions in SQLite. The database
backup capability creates one consistent single-file backup without stopping the
production MCP server.

## Online backup

The production tools are:

```text
database_backup_create(timeout_seconds = 300)
database_backup_get(backup_id)
```

`database_backup_create` uses SQLite's online backup API against the already-open
production connection. It refuses to start while that connection has an active
transaction. Concurrent committed transactions from other connections are handled
by SQLite's backup snapshot semantics.

The operation is bounded to 300 seconds by default. Callers may select 1–3,600
seconds. The backup advances in 256-page steps so timeout checks run throughout the
copy.

The destination is converted to DELETE journal mode and accepted only when no WAL,
shared-memory, or rollback-journal sidecar remains. A completed backup is therefore
one self-contained `database.sqlite3` file.

## Verification

Before publication Jacquard verifies:

- exact regular-file byte count and SHA-256;
- SQLite user schema version;
- page size and page count;
- journal mode;
- the bounded database-integrity checker (`quick_check`, foreign keys, and
  relational ownership / operation-sequence invariants);
- the exact manifest field set and canonical JSON encoding;
- an exact two-file directory layout containing only `backup-manifest.json` and
  `database.sqlite3` as regular files.

These manifest and layout rules prevent unbound data from being retained outside
the verified backup contract. Together with the database bytes and source identity
bound by `backup_id`, they also make valid concurrent stages for one backup ID have
the same retained logical size for quota admission.

Process SQLite library version is not part of backup identity, so inspection and
restore remain valid after a host upgrade when the database bytes are unchanged.

The integrity report path is normalized out before retention. Source and backup
locations are represented by opaque IDs rather than raw paths.

## Content-derived identity

The backup key binds:

```text
source database identity and opaque location ID
backup database identity
database file byte count
database file SHA-256
```

Canonical JSON of this key is hashed with SHA-256 to create the 64-character
`backup_id`. Repeating an unchanged backup reuses the same verified directory and
returns `cached=true`. Any changed database bytes, source identity, location, or
backup identity produce a different ID.

The stored manifest always has `cached=false`. Cache state returned to a caller is
response evidence and cannot be modified in an accepted immutable manifest.

## Publication, quota, and durability

A backup is staged below the backup root, verified, and then published as:

```text
<backup-root>/<backup-id>/
├── backup-manifest.json
└── database.sqlite3
```

The database file, manifest, temporary directory, and backup-root directory are
synchronized before success is returned. Publication uses the same content-derived
lock convention as other immutable artifact stores.

When `WEAVE_ARTIFACT_MAX_BYTES` is configured in the production MCP application,
verified database backups are the seventh family covered by the shared aggregate
retained-artifact quota. Backup staging is matched to the final ID through the
bounded, reverified manifest before the aggregate lock is acquired. Quota admission
then measures the exact stage, excludes any replaceable final backup, and rejects
projected overflow before entering the per-backup lock or moving the directory.

The default root is:

```text
<database-directory>/.weave-database-backups
```

Set `WEAVE_DATABASE_BACKUP_ROOT` or CLI `--backup-root` to use another location.
The environment-variable name is included in the public application manifest, and
runtime identity reports an opaque value ID when it is configured.

The standalone `weave-build db-backup` command is intentionally outside the live
MCP service composition. It is not automatically attached to the MCP process's
quota lock; operators sharing one backup root must apply an equivalent explicit
policy or use the production MCP backup tool.

## Offline restore

A live MCP server never exposes a restore tool. Replacing the database underneath
open SQLite connections would invalidate prepared state, caches, transactions, and
runtime identity.

Restore is an offline CLI operation:

```bash
weave-build --db weave.db --backup-root /backups \
  db-restore <backup-id> /new/location/restored.db
```

The source database named by `--db` does not need to exist. The CLI reads the
backup store directly, reverifies the manifest and database, copies the file into
the destination directory, reruns integrity checks, synchronizes it, and publishes
it through an atomic no-overwrite hard link.

Restore refuses:

- an existing destination;
- an existing `-wal`, `-shm`, or `-journal` sidecar;
- a destination inside the backup store;
- a corrupt backup or manifest;
- a symlinked or non-regular backup file or directory;
- an accepted backup directory containing unbound extra entries.

It never replaces an existing file. After success, start a new Jacquard process
with `WEAVE_DB_PATH` or `--db` pointing at the restored database.

The related CLI operations are:

```text
db-backup
db-backup-get <backup-id>
db-restore <backup-id> <new-destination>
```

## Error contracts

Creation can fail with:

- `DATABASE_BACKUP_TRANSACTION_ACTIVE`;
- `INVALID_DATABASE_BACKUP_TIMEOUT`;
- `DATABASE_BACKUP_TIMEOUT`;
- `DATABASE_BACKUP_FAILED`;
- `DATABASE_BACKUP_INTEGRITY_FAILED`;
- `DATABASE_BACKUP_SIDECAR_RETAINED`;
- `ARTIFACT_STORAGE_QUOTA_EXCEEDED` and bounded quota-stage failures when the
  production aggregate quota is enabled.

Restore can fail with:

- `INVALID_DATABASE_BACKUP_ID`;
- `INVALID_DATABASE_RESTORE_DESTINATION`;
- `DATABASE_RESTORE_DESTINATION_EXISTS`;
- immutable artifact or database-integrity failures.

A failed creation publishes no backup directory. A failed restore leaves no final
destination and removes its temporary copy.

## Operational boundary

Database backup protects SQLite state only. It does not include:

- committed or candidate build artifacts;
- test runs, test batches, qualifications, or attestations;
- external qualification evidence;
- compiler, sandbox, or package binaries;
- remote replication or geographic redundancy;
- retention or garbage collection.

A complete disaster-recovery plan must preserve the verified database backup,
retained artifact roots, qualification evidence, software versions, runtime
identity, and operator configuration together.

Backup-store listing, remote-copy verification, retention, and guarded deletion
remain separate operator capabilities.
