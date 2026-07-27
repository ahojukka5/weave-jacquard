# Tested-merge state-identity attestations

Jacquard can retain a cryptographic provenance link between one virtual-candidate
behavioral qualification and the later committed two-parent merge revision.

The attestation answers one narrow question:

> Is this committed merge state exactly the same state that produced the retained
> candidate qualification?

It does not reinterpret the qualification or decide whether the merge was good.

## Workflow

```text
qualification = branch_merge_test_batch_run(
  project = "demo",
  target_branch = "main",
  source_branch = "feature",
  test_targets = ["smoke"],
  preview_id = preview.preview_id
)

merged = branch_merge(
  project = "demo",
  target_branch = "main",
  source_branch = "feature",
  preview_id = preview.preview_id
)

attestation = tested_merge_attest(
  qualification_id = qualification.qualification_id,
  merged_revision_id = merged.revision_id
)
```

Use `tested_merge_attestation_get` to re-read and reverify the retained
attestation.

## Exact identity checks

The qualification subject already binds:

- project;
- target and source branches;
- common-base revision;
- exact target-head and source-head revisions;
- deterministic preview ID;
- virtual merged-state root hash;
- `committed_revision_id = null`.

The attestation accepts only a committed revision in the same project whose:

- first parent is the exact qualified target head;
- second parent is the exact qualified source head;
- stored root hash equals the qualified virtual merged-state root hash.

A revision with the same content but different parents is not the same merge
provenance and is rejected. A revision with the correct parents but different
content is also rejected.

## Content-derived attestation

The attestation ID is derived from:

- qualification ID;
- qualification manifest hash;
- original qualification status;
- complete virtual-candidate subject;
- committed revision ID, project, parent IDs, and root hash.

Repeated publication of the same valid relation reuses the same attestation.
Every read reverifies the complete qualification manifest and current immutable
revision row before returning evidence.

## Status preservation

Passing, failed, and incomplete qualifications may all be attested truthfully.
The attestation preserves:

- original aggregate status;
- `all_passed` value;
- selected, passed, failed, and error counts;
- caller-ordered selected test names.

A failed qualification does not become passing merely because its exact state was
later merged. The attestation reports both facts independently:

```text
state_identity_verified = true
qualification_status = failed
all_selected_tests_passed = false
```

## Interpretation boundary

A tested-merge attestation proves only exact state identity and parent provenance.
It does not prove:

- complete semantic test coverage;
- correctness of unselected behavior;
- merge-policy or compiler-preflight admission;
- human approval;
- production readiness;
- that the qualification should have been merged;
- that later descendant revisions remain equivalent.

The attestation creates no project revision, moves no branch, and publishes no
merge. It is an immutable external evidence artifact over already committed
state.
