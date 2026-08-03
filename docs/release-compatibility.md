# Release compatibility review

Release qualification can compare the newly retained public manifests with a
previous accepted qualification evidence directory. The comparison verifies the
retained evidence index and checksums before producing separate deterministic
tool and application compatibility reports.

Run the review directly with:

```console
weave-release-compatibility PREVIOUS_EVIDENCE CURRENT_EVIDENCE \
  --output CURRENT_EVIDENCE/compatibility-review.json
```

Exit status `0` means every changed report has an exact reviewed disposition.
Exit status `3` means the report was written but one or more changes still need
review. Invalid or tampered evidence exits with status `2`.

## Qualification integration

Set `WEAVE_PREVIOUS_RELEASE_EVIDENCE` when running `scripts/qualify-release.sh`.
The wrapper retains `compatibility-review.json`, regenerates `SHA256SUMS`, and
blocks with exit status `3` when changed manifests lack an accepted policy.
Set `WEAVE_COMPATIBILITY_POLICY` to the reviewed policy file after inspecting
the first report.

## Policy format

A policy accepts only the exact content-addressed report that was reviewed. A
changed diff ID or classification cannot reuse an older approval.

```json
{
  "format": "weave-jacquard-compatibility-policy-v1",
  "reviewed_by": "release-reviewer",
  "reviewed_at": "2026-08-03T11:00:00Z",
  "reviews": [
    {
      "manifest": "tool",
      "compatibility_diff_id": "<64 lowercase hexadecimal characters>",
      "classification": "additive-compatible",
      "decision": "accept",
      "reason": "Intentional optional tool input added for this release."
    }
  ]
}
```

Every changed tool or application report needs its own entry. Unchanged reports
must not have policy entries. The reviewer identity, timestamp, policy hash,
reason, report IDs, classifications, old and new release revisions, and final
decisions are retained in the compatibility review evidence.
