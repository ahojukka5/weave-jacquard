# Affected-target merge validation sets

## Purpose

Validating one manually selected program is insufficient when a changed source
feeds several revisioned named targets. `branch_merge_validate_affected` combines
directional impact with authoritative frontend validation so every affected
target surviving in the candidate is checked before publication.

```text
branch_merge_preflight
→ policy-aware complete validation set
→ branch_merge using returned publication_arguments
```

The validation-set operation is read-only. It creates no revision, branch update,
build manifest, executable, or retained compiler artifact.

## Public request

```text
branch_merge_validate_affected(
  project,
  target_branch,
  source_branch,
  preview_id = optional reviewed preview,
  allow_uncovered_documents = false,
)
```

The public low-level tool uses the global compiler fanout ceiling of 64. The
internal service additionally accepts an effective `max_target_validations` used
by policy-aware preflight and publication.

A stale preview returns `STALE_MERGE_PREVIEW`; a merge conflict returns
`MERGE_CONFLICT` before compiler startup.

## Target selection

Affected entries come from complete directional impact analysis in deterministic
name order.

- candidate targets are validated;
- removed targets are reported in `skipped_removed_targets`;
- unaffected targets are not invoked;
- every selected target is attempted even when an earlier target fails;
- compiler fanout is bounded before the first compiler starts.

The global ceiling is 64. A configured target policy may choose a lower effective
ceiling from 1 through 64. Exceeding it returns
`TOO_MANY_AFFECTED_TARGETS` before compiler startup.

The effective `max_target_validations` appears in the result and participates in
`validation_set_id`. Two otherwise identical candidates reviewed under different
ceilings therefore produce different evidence identities.

## Coverage gate

Changed program documents not referenced by any target surviving in the
candidate appear in `uncovered_changed_documents`.

By default:

```text
coverage_passed = false
validated_target_count = 0
ready_for_publication = false
```

Zero compiler work is deliberate: partial validation cannot make an uncovered
candidate ready.

`allow_uncovered_documents=true` records explicit acceptance of the gap. It does
not claim those documents were validated. Policy-aware preflight allows the flag
only when the authoritative target policy permits it.

## Individual validations

For each selected target:

```text
candidate target + ordered canonical sources
→ weavec --frontend
```

Compact evidence includes:

- target and impact reasons;
- changed source documents;
- deterministic individual validation ID;
- ordered documents;
- compiler SHA-256;
- availability, validity, return code, and timeout;
- diagnostic and bounded stderr;
- WIR SHA-256 and byte count.

A failed or unavailable earlier target does not hide later failures.

## Aggregate result

`weave-merge-validation-set-v1` reports:

- preview, ancestor, both heads, and merged root;
- directional changed and covered documents;
- uncovered policy and coverage result;
- effective `max_target_validations`;
- total affected and surviving target counts;
- removed targets skipped;
- validated, passed, failed, and unavailable counts/names;
- compact target records;
- `ready_for_publication`.

A set is ready only when:

```text
coverage passed
AND every surviving affected target was attempted
AND every attempted target was available and valid
```

Zero surviving affected targets form a valid empty compiler set only when
coverage passes.

## Validation-set identity

`validation_set_id` binds:

```text
format
+ preview ID
+ prospective merged-root hash
+ uncovered policy and list
+ effective max-target-validations ceiling
+ ordered surviving target names
+ removed target names
+ ordered individual validation IDs
```

The same candidate, compiler identities, source hashes, target graph, ceiling,
and uncovered policy produce the same identity.

The set is evidence, not a bearer token. Publication recomputes either the set or
policy-aware preflight before writing.

## Publication paths

### Direct all-target mode

```text
branch_merge(
  project,
  target_branch,
  source_branch,
  preview_id,
  validate_affected_targets = true,
  allow_uncovered_documents = false)
```

When target policy permits this mode, publication recomputes impact, applies the
effective ceiling, validates all selected targets, enforces readiness, and
atomically rechecks both heads.

### Policy-aware preflight replay

```text
branch_merge(
  ...,
  validate_affected_targets = true,
  preflight_id = reviewed preflight)
```

Publication recomputes policy-aware preflight once, compares exact identity, and
reuses its validation set for publication. It does not launch a redundant second
compiler fanout before the same transactional head check.

## Failure codes

- `INVALID_AFFECTED_TARGET_LIMIT`: effective limit outside 1–64;
- `TOO_MANY_AFFECTED_TARGETS`: surviving affected count exceeds effective limit;
- `MERGE_UNCOVERED_DOCUMENTS`: coverage failed without permitted override;
- `MERGE_VALIDATION_UNAVAILABLE`: one or more compiler validations unavailable;
- `MERGE_VALIDATION_FAILED`: one or more targets rejected;
- `INCOMPLETE_MERGE_VALIDATION_SET`: completeness invariant failed;
- `STALE_MERGE_PREVIEW`: branch heads changed;
- `MERGE_CONFLICT`: stable-ID merge is not clean.

Configured target policies may reject the selected mode earlier. Every failure
leaves the target branch unchanged.

## Compatibility

`branch_merge` preserves direct, one-target, and all-target modes where the
effective target policy permits them. Reviewed protected-branch work should use
`branch_merge_preflight` and its returned arguments. The low-level validation-set
tool remains useful for focused investigation.
