# Retained-artifact lifecycle runbook

This runbook defines the operator workflow for retention planning, quarantine,
holding-period verification, restore, and permanent deletion. The workflow is
evidence-first and deliberately has no automatic background deletion.

## Safety model

The lifecycle has four separate mutation boundaries:

1. `weave-artifact-retention-plan` is read-only and produces a deterministic
   dry-run plan bound to one exact complete reconciliation.
2. `weave-artifact-quarantine` moves one exact selected entry into a verified
   family-local quarantine capsule. It does not permanently delete payload data.
3. `weave-artifact-quarantine-restore` moves one exact verified payload back to
   its original family-local name without overwriting live content.
4. `weave-artifact-quarantine-delete` permanently removes only an explicit,
   bounded batch of capsules that already passed a separate holding-period
   verification.

All destructive commands are operator-only console commands. They are not MCP
mutations. Database files are never lifecycle deletion targets.

A logical-byte report is not a physical free-space guarantee. Sparse files,
filesystem metadata, snapshots, deduplication, compression, and delayed block
reclamation can make physical usage differ.

## 1. Capture reconciliation

Run:

```bash
weave-artifact-reconcile > reconciliation.json
```

The report must be complete and contain a `reconciliation_id`. Resolve corrupt,
unknown, or changing storage before continuing. Reachable evidence and missing
required evidence are never eligible for retention-plan selection.

## 2. Write an explicit retention policy

A policy names the exact `reconciliation_id` and contains bounded rules by:

- artifact family;
- reconciliation classification;
- minimum artifact age;
- minimum retained count;
- protected artifact identities.

Example:

```json
{
  "format": "weave-artifact-retention-policy-v1",
  "reconciliation_id": "<64-hex reconciliation id>",
  "rules": [
    {
      "family": "committed_builds",
      "classification": "orphaned",
      "minimum_age_seconds": 604800,
      "minimum_retained_count": 2,
      "protected_artifact_ids": []
    }
  ]
}
```

## 3. Generate the dry-run plan

Run:

```bash
weave-artifact-retention-plan \
  --policy retention-policy.json \
  --as-of-unix-ns <explicit timestamp> \
  > retention-plan.json
```

The plan performs no mutation. Review its ordered entries, projected logical
byte recovery, family totals, rules, limits, `policy_id`, and `plan_id`. Do not
edit the generated plan. Any filesystem, database, policy, or reconciliation
change requires a fresh reconciliation and plan.

## 4. Quarantine selected entries

For each approved plan entry, run:

```bash
weave-artifact-quarantine \
  --policy retention-policy.json \
  --plan retention-plan.json \
  --entry-id <selected entry id> \
  > quarantine-result.json
```

Save the returned `quarantine_id`, `quarantine_entry_id`, and `manifest_id`.
Quarantine journals intent before source mutation, holds the normal source
publication lock, moves by family-local rename, verifies the payload after the
move, synchronizes directory metadata, and is idempotent. Re-running the exact
same request resumes an interrupted publication or returns the same completion
evidence.

## 5. Observe the holding period

Choose and record an operator holding policy, such as seven days. Verification
uses an explicit timestamp so the evidence is reproducible:

```bash
weave-artifact-quarantine-verify \
  --quarantine-id <quarantine id> \
  --manifest-id <manifest id> \
  --plan-id <plan id> \
  --minimum-holding-seconds 604800 \
  --as-of-unix-ns <explicit timestamp> \
  > quarantine-verification.json
```

Verification is read-only. It reverifies the durable journal, exact manifest,
current quarantine classification, current database reachability, bounded
no-follow payload snapshot, and holding deadline. It fails if the artifact is
currently required, the capsule changed, the current state changes during the
scan, or the holding period is incomplete.

Save the returned `verification_id` together with the exact holding duration and
`as_of_unix_ns`. Changing either value produces different verification evidence.

## 6A. Restore instead of deleting

Before deletion, an operator may restore the capsule:

```bash
weave-artifact-quarantine-restore \
  --quarantine-id <quarantine id> \
  --manifest-id <manifest id> \
  > restore-result.json
```

Restore rejects an occupied original name. It journals intent before moving the
payload, verifies before and after the rename, removes only obsolete quarantine
metadata, and replays idempotently after interruption. A successful restore
makes the payload live again and invalidates deletion of that capsule.

## 6B. Permanently delete an explicit bounded batch

Create a request containing only exact reviewed identities:

```json
{
  "format": "weave-artifact-quarantine-delete-request-v1",
  "entries": [
    {
      "quarantine_id": "<64-hex quarantine id>",
      "manifest_id": "<64-hex manifest id>",
      "plan_id": "<64-hex plan id>",
      "verification_id": "<64-hex verification id>",
      "minimum_holding_seconds": 604800,
      "as_of_unix_ns": 0
    }
  ]
}
```

Use the exact `as_of_unix_ns` from verification, not zero. Then run:

```bash
weave-artifact-quarantine-delete \
  --request delete-request.json \
  > delete-result.json
```

Deletion is irreversible. The command:

- accepts at most 100 explicit caller-ordered entries;
- requires exact plan, quarantine, manifest, and verification identities;
- journals delete intent before removing payload data;
- rechecks current database state before starting or resuming;
- removes files, directories, special entries, and symlinks without following
  links;
- uses the scan and depth bounds recorded by the exact plan;
- synchronizes affected directories;
- records durable completion evidence outside retained roots;
- replays successful entries idempotently;
- reports every entry independently.

The process exits with status 3 when any entry fails. A partial batch has
`complete = false`, even when some sibling entries were deleted successfully.
Re-run the exact same request to replay successes and retry unresolved entries.
Do not infer global success from a zero per-entry error count in a truncated or
modified request.

## Storage accounting

`artifact_storage_report` preserves complete aggregate logical-byte quota
accounting and additionally reports:

- `usage.retained_logical_bytes`;
- `usage.quarantined_logical_bytes`.

The two values sum to aggregate logical bytes. Quarantine accounting applies
only to exact reserved top-level capsule names. Similar-looking unknown names
remain retained usage and are not treated as valid quarantine evidence.

## Failure recovery

### Stale plan or changed source

Do not edit the plan or journal. Capture a fresh reconciliation, review why state
changed, regenerate policy/plan evidence, and make a new explicit decision.

### Interrupted quarantine

Re-run the exact same policy, plan, and entry ID. The durable intent and staging
capsule are the recovery record. Do not rename staging directories manually.

### Holding period not met

Keep the capsule quarantined. After the operator policy duration has elapsed,
run verification with a new explicit `as_of_unix_ns` and use the newly returned
`verification_id`.

### Corrupt or changed quarantine capsule

Permanent deletion must remain blocked. Preserve the capsule and control
metadata for investigation. Restore is permitted only if its exact verification
succeeds. Never bypass verification by deleting paths manually.

### Restore destination exists

Inspect the live destination. Do not overwrite it. Decide whether the live entry
is authoritative, move it through a separately reviewed process, or abandon the
restore. Re-run the exact restore only after the destination conflict is gone.

### Interrupted restore

Re-run the exact quarantine and manifest identities. Restore completion evidence
and metadata cleanup are resumable and idempotent.

### Interrupted permanent deletion

Re-run the exact delete request. The durable delete intent authorizes continued
removal of only that capsule. If the database snapshot changed after intent,
deleting stops and requires operator investigation rather than silently
continuing.

### Partial delete batch

Read every ordered outcome. Successful entries are durable and replayable;
failed entries retain structured error evidence. Correct the external cause and
re-run the same request. The command remains nonzero until the whole request is
complete.

### Symlink or special entry

Lifecycle scans and deletion use `lstat`/no-follow behavior. A symlink target is
never traversed or deleted. Unexpected capsule top-level entries, non-regular
metadata, scan-limit overflow, and depth overflow fail closed.

## Pull-request completion gate

A pull request remains a draft while its referenced issue still has unimplemented
acceptance criteria or while any required CI job is queued, running, cancelled,
or red. Do not stop at a partial slice and call it ready.

Mark a pull request ready for review only when:

1. its body uses `Closes #<issue>` for the issue it fully completes;
2. every acceptance criterion is implemented or explicitly removed from scope by
   the issue owner;
3. the exact final head has passed all required portable and packaged CI gates;
4. the full final diff and commit structure have been reviewed;
5. validation evidence in the PR body matches the exact final head.

When CI is red, the work is unfinished: diagnose, fix, rerun, and continue until
all required checks are green. When CI is queued or running, wait and check the
terminal result before changing review state.
