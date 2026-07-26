# Affected-target merge validation sets

## Purpose

Validating one manually selected program is not sufficient when a changed source
feeds several revisioned named targets. `branch_merge_validate_affected` combines
merge impact analysis with authoritative frontend validation so every affected
target surviving in the candidate is checked before publication.

```text
branch_merge_preview
→ branch_merge_impact
→ branch_merge_validate_affected
→ branch_merge(validate_affected_targets = true)
```

The validation-set operation is read-only. It creates no revision, branch update,
build manifest, executable, or retained compiler artifact.

## Request

```text
branch_merge_validate_affected(
  project,
  target_branch,
  source_branch,
  preview_id = optional reviewed preview,
  allow_uncovered_documents = false,
)
```

The service recomputes the exact directional target impact for the current merge
candidate. A stale preview returns `STALE_MERGE_PREVIEW`; a semantic merge
conflict returns `MERGE_CONFLICT` before compiler startup.

## Target selection

Affected target entries come from `branch_merge_impact` in deterministic name
order.

- targets that exist in the candidate are validated;
- removed targets are reported in `skipped_removed_targets` but cannot be
  validated because no candidate definition remains;
- unaffected targets are not invoked;
- compiler fanout is limited to 64 surviving affected targets per call.

A larger set returns `TOO_MANY_AFFECTED_TARGETS` before starting a compiler. The
bound prevents a single MCP request from becoming an unbounded process launcher.

## Coverage gate

Changed program documents not referenced by any target surviving in the
candidate appear in `uncovered_changed_documents`.

By default, uncovered documents fail coverage before any target validation:

```text
coverage_passed = false
validated_target_count = 0
ready_for_publication = false
```

This is deliberate. Running some target validations would waste compiler work
while still leaving the candidate incomplete as a reviewed target graph.

`allow_uncovered_documents=true` is an explicit override. The uncovered list is
still returned and participates in validation-set identity. The override does
not pretend those documents were validated; it records that the caller accepted
the gap.

## Individual validations

For each selected target, Jacquard invokes the same exact-candidate service used
by `branch_merge_validate`:

```text
candidate target + ordered canonical sources
→ weavec --frontend
```

The public validation set includes compact per-target evidence:

- target name;
- impact reasons and changed source documents;
- deterministic individual validation ID;
- ordered documents;
- compiler SHA-256;
- availability, validity, return code, and timeout state;
- diagnostic and bounded stderr;
- WIR SHA-256 and byte count.

All selected targets are attempted. A failed or unavailable earlier target does
not hide later failures. This gives reviewers the complete bounded failure set in
one response.

## Aggregate result

`weave-merge-validation-set-v1` reports:

- preview, ancestor, both heads, and merged root;
- directional changed and covered document sets;
- uncovered-document policy and coverage result;
- total affected and surviving affected target counts;
- removed targets skipped;
- validated, passed, failed, and unavailable counts and names;
- compact target validation records;
- `ready_for_publication`.

A set is ready only when:

```text
coverage passed
AND every surviving affected target was attempted
AND every attempted target was available and valid
```

Zero surviving affected targets form a valid empty compiler set only when
coverage passes. This supports metadata-only or explicitly allowed uncovered
merges without inventing a fake target.

## Validation-set identity

The deterministic `validation_set_id` binds:

```text
format
+ preview ID
+ prospective merged root hash
+ uncovered-document policy and list
+ ordered surviving affected target names
+ removed target names
+ ordered individual validation IDs
```

The same candidate, compiler identities, source hashes, target graph, and policy
produce the same set identity.

Like an individual validation response, the set is evidence rather than a bearer
token. Publication repeats the complete validation set.

## Publication gate

```text
branch_merge(
  project,
  target_branch,
  source_branch,
  preview_id,
  validate_affected_targets = true,
  allow_uncovered_documents = false,
)
```

Publication performs:

1. exact impact recomputation;
2. coverage enforcement;
3. bounded validation of all surviving affected targets;
4. aggregate readiness enforcement;
5. use of the validation set's preview ID;
6. atomic recheck of both heads inside merge publication;
7. immutable two-parent revision creation.

The response records `affected_validation_enforced`, the uncovered-document
policy, and the complete validation set.

## Failure codes

- `MERGE_UNCOVERED_DOCUMENTS`: coverage failed and no override was supplied;
- `TOO_MANY_AFFECTED_TARGETS`: more than 64 surviving targets require validation;
- `MERGE_VALIDATION_UNAVAILABLE`: at least one selected target lacked compiler
  validation;
- `MERGE_VALIDATION_FAILED`: at least one selected target was rejected;
- `INCOMPLETE_MERGE_VALIDATION_SET`: internal completeness invariant failed;
- `STALE_MERGE_PREVIEW`: either branch advanced;
- `MERGE_CONFLICT`: stable-ID merge was not clean.

Every failure leaves the target branch unchanged.

## Validation modes

`branch_merge` preserves three modes:

- direct structural merge;
- one explicit `validation_target`;
- `validate_affected_targets=true`.

A call cannot combine the single-target and all-target modes.
`allow_uncovered_documents` is meaningful only with all-target validation.
Ambiguous combinations return `INVALID_MERGE_VALIDATION_MODE`.

Reviewed parallel-agent work should use the all-affected mode. Single-target
validation remains useful for focused investigation and compatibility.
