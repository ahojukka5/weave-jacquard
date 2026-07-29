# Database integrity

Jacquard schema version 3 combines SQLite relational constraints with bounded
semantic verification of immutable program history.

## Read-only inspection

Inspect an existing database without opening a workspace or running migrations:

```bash
weave-build --db /path/to/weave.db db-check
```

The command opens SQLite with `mode=ro` and returns
`weave-database-integrity-v1` JSON. The report names the exact semantic proof
contract as:

```text
weave-database-semantic-integrity-v1
```

The outer report format can retain compatible operational fields while the semantic
contract identifies the exact snapshot, hash, operation, context, and history
invariants being claimed. Exit status is:

- `0` when `valid = true`;
- `1` when the database was read but integrity issues were found;
- `2` when the file could not be opened or inspected.

`db-check` does not create a database, change journal mode, install triggers,
advance schema version, or repair data.

## Relational verification

The checker verifies:

- stored `PRAGMA user_version` and required schema objects;
- SQLite `quick_check` results;
- foreign-key violations;
- cross-project first and second revision parents;
- missing branch projects and cross-project branch heads;
- duplicate operation sequence numbers within one revision.

Schema-v3 triggers and indexes enforce these relationships for normal writes and
direct SQLite writes.

## Semantic revision verification

Every revision is reconstructed from its retained module snapshots in lexical
qualified-name order. The checker:

- decodes each raw or zlib snapshot through the bounded shared codec;
- rejects unsupported prefixes, invalid streams, truncation, trailing bytes,
  invalid UTF-8, invalid JSON, and non-object roots;
- validates every decoded S-expression tree through the production structural
  limits;
- canonicalizes each tree and compares its SHA-256 with `ast_hash`;
- reconstructs the complete module mapping and compares its SHA-256 with the
  revision `root_hash`;
- validates qualified module names;
- requires operation sequence numbers to begin at zero and remain contiguous;
- parses every operation payload as a JSON object and requires canonical encoding;
- recomputes every context-document `content_hash`;
- detects cycles across first and second revision parents.

Normal production workspace reads use the same snapshot codec and hash
reconstruction. A corrupt retained state fails with the stable
`CORRUPT_REVISION_STATE` domain error rather than being returned to rendering,
build, merge, test, CLI build, or agent-inspection code.

## Resource ceilings

The current semantic limits are:

| Dimension | Limit |
|---|---:|
| compressed bytes in one snapshot blob | 16 MiB |
| decoded bytes in one snapshot | 32 MiB |
| modules in one revision | 4,096 |
| aggregate decoded snapshot bytes in one revision | 256 MiB |
| UTF-8 bytes in one qualified module name | 4,096 |
| retained examples per issue category | 20 |

Exact-limit values are admitted. Limit-plus-one values fail closed. Internal
completeness overflow never returns a valid partial revision or a plausible root
identity.

The report includes complete issue counts, bounded examples, semantic scan metrics,
and the effective limit set. `examples_truncated` distinguishes response truncation
from the complete finding count.

## Migration admission

Opening an older database validates relational and semantic integrity before any
schema-v3 object is created or `user_version` is advanced.

A legitimate legacy database may lack `module_snapshots_compressed` while it still
contains the uncompressed `module_snapshots` table. Legacy `ast_json` rows are
parsed, structurally validated, hash-checked, and included in revision-root
reconstruction before migration begins. Only that known missing-table transition is
allowed.

Migration stops on any relational or semantic finding, including malformed legacy
snapshot JSON, AST hash mismatch, root hash mismatch, invalid operation payload,
context hash mismatch, or parent cycle. A rejected migration leaves the legacy
schema version and data unchanged.

## Backup and restore integration

`database_backup_create` applies the complete checker to the consistent online copy
before publication. A source whose bytes can be copied but whose immutable program
history is semantically corrupt is rejected with
`DATABASE_BACKUP_INTEGRITY_FAILED`.

`database_backup_get` rehashes the retained file and reruns the same semantic
checker. Offline `db-restore` verifies the copied destination again before atomic
publication to a new path. The stored integrity report is path-normalized and must
match the newly observed report exactly.

The semantic contract identifier is also bound into the content-derived backup key.
A backup created under an older proof contract cannot collide with or silently be
presented as a backup verified under the current semantic contract.

A verified backup therefore proves, within the documented limits:

- SQLite file and relational integrity;
- bounded decodability and structural validity of every module snapshot;
- every snapshot `ast_hash`;
- every revision `root_hash`;
- canonical operation payloads and contiguous operation order;
- context-document hashes;
- acyclic revision parent history.

Backup and restore remain non-repairing operations. Corrupt evidence is rejected,
not rewritten.

## Remaining operations work

Database semantic integrity does not provide:

- retained-artifact reachability reconciliation;
- remote backup replication and verification;
- backup-store listing, retention, quarantine, or guarded deletion;
- automatic repair;
- live in-place database replacement.

Those operations must preserve the same evidence-first rule: inspect before
mutation, fail closed on incomplete scans, and require explicit operator authority
for destructive actions.
