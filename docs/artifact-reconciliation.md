# Retained-artifact reconciliation

Jacquard reconciles the live SQLite history with every configured retained-artifact
family through one bounded, deterministic, read-only report. The report answers
which verified evidence is still connected to immutable database history and which
filesystem entries require operator attention. It does not authorize deletion.

The public surfaces are:

- MCP tool `artifact_reconciliation_report`;
- operator command `weave-artifact-reconcile`.

The MCP tool returns the normal Jacquard envelope:

```json
{
  "ok": true,
  "result": {
    "format": "weave-artifact-reconciliation-v1",
    "complete": true,
    "reconciliation_id": "..."
  }
}
```

The command prints the report object directly as deterministic JSON on standard
output. Domain failures are printed as structured JSON on standard error and exit
with status 2. Both surfaces use the same runtime-owned production service.

## Included artifact families

Reconciliation always composes the seven production retained stores from their
active services. It does not independently reconstruct roots from environment
variables.

| Family | Production verification | Direct database anchor | Typed references |
|---|---|---|---|
| `committed_builds` | committed build `get(...)` | matching project and revision | none |
| `candidate_builds` | merge-candidate build `get(...)` | matching project plus base, target-head, and source-head revisions | none |
| `test_runs` | committed test-run `get(...)` | matching project and revision | committed build |
| `test_batches` | committed test-batch `get(...)` | matching project and revision | member test runs |
| `candidate_test_qualifications` | candidate qualification `get(...)` | matching project plus base, target-head, and source-head revisions | candidate builds |
| `tested_merge_attestations` | tested-merge attestation `get(...)` | matching merged project and revision | candidate qualification |
| `database_backups` | verified database-backup `get(...)` | source location ID equals the live database location ID | none |

Six families use their normal 32-hex artifact identifiers. Verified database
backups use their normal 64-hex content-derived identifiers. An artifact-shaped
name is never accepted by name alone: its production `get(...)` path must reread
and semantically verify the retained evidence.

## Database snapshot

The database side is inspected through a separate SQLite connection opened with
`mode=ro`, `PRAGMA query_only = ON`, and an explicit read transaction. The snapshot
must pass the strongest semantic integrity contract before any reachability result
is accepted.

Projects and revisions are read in deterministic order. The database identity
binds:

- the semantic-integrity contract and schema version;
- project IDs and names;
- revision IDs, owning projects, parents, and root hashes.

Jacquard takes the database snapshot both before and after artifact verification.
If the two database snapshot IDs differ, reconciliation fails with
`ARTIFACT_RECONCILIATION_DATABASE_CHANGED`. A report therefore never combines one
artifact inventory with two different database histories.

## Filesystem inventory

Each configured family root must be a real directory and must not be a symlink.
Jacquard enumerates direct entries with `follow_symlinks=False`, records stable
metadata for a before-and-after comparison, and sorts the snapshots before
classification. It never opens a symlink target or treats a special file as an
artifact.

Nested production roots are owned by their most specific family. The parent scan
counts the nested root during bounded enumeration but excludes that subtree from
its catalog; the child family owns its entries. Equal roots are rejected because
ownership would be ambiguous.

A family is rejected if its entry snapshot changes during verification. This
catches concurrent publication, replacement, or cleanup rather than assigning a
complete catalog identity to mixed filesystem states.

## Classification semantics

Every physical entry receives exactly one inventory classification. Verified
entries are then refined to reachable or orphaned, and absent dependencies may add
synthetic missing records.

### `reachable`

The physical artifact passed its production verifier and either:

- all of its required immutable revision anchors exist under the recorded project;
- it is a same-location verified backup of the live database; or
- it is referenced by another reachable verified artifact through one of the typed
  relationships in the family table.

Reachability propagates from a reachable evidence record to the artifacts it
references. For example, a reachable test batch makes its present verified test
runs reachable, and a reachable test run makes its present verified committed
build reachable.

### `orphaned`

The physical artifact passed its production verifier but has no valid direct
anchor and is not reached from another reachable artifact. Orphaned means
"currently disconnected from the inspected database history". It is evidence for
retention policy, not permission to delete.

### `missing`

A reachable verified artifact references an artifact ID for which no physical entry
exists in the target family. The record contains a complete `required_by_count` and
bounded `required_by` examples.

If any physical entry with that family and artifact ID exists, Jacquard does not
also call it missing. A malformed or corrupt physical artifact remains corrupt so
operators see the actual condition rather than a double count.

### `corrupt`

The entry has an artifact-shaped ID but is not a directory, or its normal production
verifier rejects it. The bounded example retains only a stable error code, such as
a verifier validation code or `ARTIFACT_INTEGRITY_ERROR`; exception text and raw
paths are not included.

Corrupt manifests, wrong retained hashes, missing required files, and other
production admission failures therefore use the same classification boundary as a
normal artifact read.

### `staging`

The entry name is dot-prefixed and is not recognized as quarantine or lock state.
Age does not change this classification: an old interrupted stage remains visible
as staging until an explicit, separately authorized workflow handles it.

### `quarantined`

The name contains `.replaced-` or `.quarantine-`. Reconciliation only observes this
state. It does not create, move, restore, or delete quarantine entries.

### `lock_internal`

The name ends in `.lock` or begins with `.lock-`. Lock files are reported separately
from retained evidence and generic root pollution.

### `unknown`

The entry is outside the recognized artifact and internal-name contracts. This
includes malformed names, symlinks, sockets, FIFOs, devices, and other special
files. Symlinks and special files are never passed to a production verifier and
never become reachable artifacts.

## Counts and examples

Counts are complete for every classification. Examples are bounded independently
and never replace full counts. Each family reports:

- physical and synthetic-missing entry counts;
- complete classification counts;
- bounded path-redacted examples;
- a content-derived `family_reconciliation_id`.

The aggregate reports physical entries, synthetic missing entries, total catalog
entries, typed relationship count, and complete classification counts across all
seven families.

## Bounds and fail-closed behavior

One report uses the following default ceilings:

| Boundary | Limit |
|---|---:|
| configured families | 16 |
| entries across all roots | 1,000,000 |
| entries in one family | 250,000 |
| database projects | 100,000 |
| database revisions | 1,000,000 |
| typed artifact relationships | 2,000,000 |
| examples per classification | 25 |

An exact ceiling succeeds. The next entry, project, revision, or relationship fails
the operation. Root unavailability, invalid roots, enumeration failures, database
integrity failures, and concurrent changes also fail the operation.

A failed or truncated operation returns no `reconciliation_id`. MCP returns a
structured error without a `result`; the CLI emits a structured error on standard
error. Operators must not reuse an older ID as evidence for the failed scan.

## Redaction and deterministic identity

Raw database paths, artifact roots, and unrecognized entry names are absent from
public responses. Jacquard emits domain-separated opaque IDs for:

- the live database location;
- every family root;
- every observed or synthetic entry.

These IDs allow equality comparison without publishing paths. Path-derived values
may have low entropy, so the IDs are matching evidence rather than secret-storage
primitives.

`reconciliation_id` is SHA-256 over canonical JSON that binds:

- the complete database snapshot ID;
- the complete inventory ID;
- every family record;
- verified manifest hashes;
- immutable revision anchors;
- typed artifact references, including complete missing dependency relationships.

Filesystem entries, projects, revisions, relationships, families, and examples are
ordered deterministically before hashing or publication. The report contains no
timestamp or random value. Repeated scans of unchanged database history, roots,
files, and verified manifests therefore produce the same ID regardless of native
filesystem enumeration order.

## Read-only policy boundary

Reconciliation reads and verifies evidence. It does not:

- repair manifests or hashes;
- create or remove staging directories;
- move artifacts into or out of quarantine;
- delete reachable, orphaned, corrupt, or unknown entries;
- apply age-based retention;
- measure physical filesystem blocks;
- replicate artifacts or database history.

Any future retention or garbage-collection workflow must consume a fresh complete
report, define separate policy and authorization, revalidate its preconditions, and
remain outside this read-only capability. See
[artifact storage accounting](artifact-storage.md) and
[aggregate artifact quota](artifact-quota.md) for the separate accounting and
publication-admission contracts.
