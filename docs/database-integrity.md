# Database integrity

Jacquard schema version 3 moves project-graph ownership and operation ordering
from application convention into the SQLite boundary.

## Read-only inspection

Inspect an existing database without opening a workspace or running migrations:

```bash
weave-build --db /path/to/weave.db db-check
```

The command opens SQLite with `mode=ro` and returns
`weave-database-integrity-v1` JSON. Exit status is:

- `0` when `valid = true`;
- `1` when the database was read but integrity issues were found;
- `2` when the file could not be opened or inspected.

The report includes:

- the stored `PRAGMA user_version`;
- bounded issue categories and examples;
- SQLite `quick_check` results;
- foreign-key violations;
- cross-project first and second revision parents;
- missing branch projects;
- cross-project branch heads;
- duplicate operation sequence numbers within one revision.

At most 20 examples are returned for each issue category. Counts and
`examples_truncated` preserve the distinction between a bounded response and the
complete finding set.

`db-check` does not create a database, change journal mode, install triggers,
advance schema version, or repair data.

## Schema-v3 constraints

Schema v3 adds:

```text
UNIQUE operations(revision_id, sequence_number)
```

and deterministic triggers requiring:

- every non-null `parent1_id` revision to belong to the child's project;
- every non-null `parent2_id` revision to belong to the child's project;
- every branch project to exist;
- every branch head revision to belong to that branch's project;
- revision project changes not to orphan child revisions or branch heads.

These checks protect direct SQLite writes in addition to Jacquard's existing
application-level project checks and compare-and-set publication rules.

Branches remain mutable named pointers. Revisions, snapshots, and operation rows
remain logically immutable through the public API; schema v3 does not yet add
general update/delete denial triggers for every immutable table.

## Migration admission

Opening an older database validates relational integrity before any schema-v3
object is created or `user_version` is advanced.

Migration stops when it finds:

- a failed SQLite quick check;
- any foreign-key violation;
- a cross-project revision parent;
- a missing or cross-project branch project/head;
- duplicate operation sequence numbers;
- any missing core relational table.

A legitimate schema-v1 database may lack `module_snapshots_compressed` while it
still contains the legacy `module_snapshots` table. That one known transition is
allowed so the existing transactional snapshot migration can run. No other
missing-table finding is ignored.

A rejected migration leaves the legacy schema version and data unchanged. The
operator should run `db-check`, restore from backup, or repair a copy manually;
Jacquard does not guess how to rewrite corrupt project history.

## Open-database inspection

Internal operators and tests may call:

```python
report = database.integrity_report()
```

This runs the same checker on the already-open connection. It is read-only and
does not replace transaction-time validation.

## Remaining operations work

Schema v3 does not yet provide:

- online backup and verified restore commands;
- retained-artifact catalog reconciliation;
- snapshot JSON/hash recomputation for every revision;
- root-hash reconstruction across the complete history;
- retention and garbage collection;
- automatic repair.

Those should build on the same evidence-first rule: inspection and backup must be
non-destructive, bounded where exposed through agent interfaces, and explicit
about checks that were not performed.
