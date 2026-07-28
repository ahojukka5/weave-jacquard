# Aggregate artifact quota

Jacquard can enforce one aggregate logical-byte ceiling across every retained
artifact family published by the production MCP application.

## Configuration

Set an unsigned decimal byte count:

```text
WEAVE_ARTIFACT_MAX_BYTES=107374182400
```

The example is 100 GiB. An absent or empty value disables admission enforcement.
Zero permits no nonempty retained publication. Signs, whitespace, decimal points,
non-ASCII digits, and values above signed 64-bit range are startup errors.

The variable name is included in the content-derived public application manifest.
`runtime_identity` reports whether it is set and includes its opaque value ID
without revealing the configured value.

Every process writing to one shared artifact-root graph must use the same database
directory and quota configuration. A process with the quota disabled or a different
ceiling can intentionally admit a state another process would reject. Runtime
identity makes configuration disagreement observable, but the lock file is not a
persistent configuration registry and cannot repair mixed operator policy.

## Scope

The aggregate ceiling covers completed logical regular-file bytes in:

- committed builds;
- virtual-candidate builds;
- committed test runs;
- committed test batches;
- virtual-candidate test qualifications;
- tested-merge attestations;
- verified database backups.

All seven production publishers receive the same `ArtifactQuotaService` instance
and use a lock file in the active database directory. Processes using the same
database therefore serialize quota admission even when artifact roots are
configured outside that directory.

Processes using different database directories do not share a quota lock. An
operator who points separate Jacquard databases at overlapping artifact roots has
created unsupported independent publication domains and can exceed the intended
ceiling.

The public Python service classes and `weave-build` CLI are not silently placed
inside the MCP application's lock domain. Embedded or CLI writers sharing these
roots must either use the production composition or provide an equivalent explicit
quota guard. The current guarantee is for the composed production MCP application.

## Admission algorithm

A publisher creates its temporary artifact directory using the normal process,
protocol, checksum, and manifest limits. Immediately before atomic publication it
then:

```text
acquire aggregate quota lock
→ enumerate retained content across every configured root
→ exclude dot-prefixed internal staging, lock, and quarantine entries
→ exclude a replaceable final directory
→ measure the exact staged publication
→ calculate projected retained logical bytes
→ reject or enter the existing per-artifact publication lock
→ verify and publish atomically
→ release per-artifact lock
→ release aggregate quota lock
```

The lock order is always aggregate first, artifact-specific second. This avoids a
cycle between publishers using different artifact families.

Committed and candidate builds pass their exact temporary directory directly.
Other immutable publishers use their final ID to locate dot-prefixed temporary
directories created by the existing publication implementation. Matching-stage
discovery is bounded to 65,536 direct family-root entries and 16 duplicate staged
directories. When duplicate stages exist for the same content-derived final ID,
Jacquard uses the largest matching stage for conservative admission.

Database backup staging predates the final backup ID in its directory name. The
backup publisher therefore locates stages by reading the bounded manifest,
requiring the manifest ID to equal the final directory ID, reverifying the complete
backup, and requiring exactly `backup-manifest.json` and `database.sqlite3` as
regular files. Discovery uses the same 65,536-entry and 16-match ceilings. Multiple
valid stages with one backup ID are byte-identical because the ID binds the database
bytes, SQLite identity, source identity, and exact two-file layout.

Unrelated concurrent temporary directories are excluded from retained usage. Once
one publisher commits, the next process observes its completed final directory
while holding the same lock, so two individually acceptable publications cannot
oversubscribe the aggregate ceiling.

## Replacement and cache behavior

A final directory selected for replacement is excluded before projection because
its retained bytes disappear when the staged directory is atomically installed.
The normal publication implementation still verifies cache hits and controls
quarantine and rollback.

A cache hit that does not publish new bytes remains governed by its existing
verified-cache behavior. An invalid existing directory is not silently accepted;
normal integrity and replacement rules still apply after quota admission.

Dot-prefixed quarantine content can temporarily consume physical disk blocks while
replacement is in progress. The retained logical-byte quota governs completed
artifact state, not maximum instantaneous physical allocation.

## Failure contract

Projected overflow returns:

```json
{
  "code": "ARTIFACT_STORAGE_QUOTA_EXCEEDED",
  "message": "artifact publication would exceed the configured logical-byte quota",
  "node_id": null,
  "retryable": false,
  "requires_operator_action": true,
  "family": "committed_builds",
  "quota_bytes": 100,
  "current_bytes": 90,
  "staged_bytes": 20,
  "projected_bytes": 110
}
```

This is not a blind-retry condition. The caller must reduce retained usage, raise
the configured ceiling, or produce a smaller artifact. A later retry after explicit
operator action remeasures current state.

Other admission failures include:

- `INVALID_ARTIFACT_QUOTA_PATH`;
- `ARTIFACT_STORAGE_STAGE_NOT_FOUND`;
- `ARTIFACT_STORAGE_STAGE_LIMIT_EXCEEDED`;
- `ARTIFACT_STORAGE_QUOTA_ROOT_LIMIT_EXCEEDED`;
- `ARTIFACT_STORAGE_QUOTA_LOCK_UNAVAILABLE`;
- normal bounded storage scan failures.

No branch or revision database state is changed by artifact quota refusal because
all covered publications occur outside program-revision transactions and fail
before their final atomic directory move.

## Report evidence

`artifact_storage_report` returns the active quota alongside normal storage
accounting:

- enabled state and ceiling;
- retained `current_logical_bytes` used for admission;
- public `observed_logical_bytes`, including root-level internal staging;
- the corresponding `internal_logical_bytes` difference;
- available bytes and already-exceeded state;
- enforcement mode;
- opaque lock ID;
- retained-storage snapshot ID;
- quota policy ID;
- combined quota snapshot ID.

The public storage view and retained quota view are each bounded scans performed
under the same interprocess lock. The report is diagnostic. Publication always
remeasures under the lock rather than trusting an earlier snapshot.

## Remaining storage work

Aggregate retained logical-byte admission is not retention management. Remaining
operator capabilities include:

- verified artifact reachability and reconciliation;
- age, project, revision, and evidence-retention policy;
- explicit dry-run deletion plans;
- guarded garbage collection and quarantine recovery;
- temporary staging and physical-block limits;
- live SQLite database-size policy;
- a typed runtime container that removes the current cached-service adaptation.
