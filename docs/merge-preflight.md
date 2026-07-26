# One-call merge preflight

## Purpose

`branch_merge_preflight` is the default review entrypoint for combining independent
Jacquard branches. It composes the existing non-mutating merge layers into one
bounded deterministic result:

```text
stable-ID merge preview
+ directional named-target impact
+ candidate coverage analysis
+ complete affected-target frontend validation
= merge preflight evidence
```

The tool does not create a revision, update a branch, retain compiler output, or
publish a build artifact.

## Request

```text
branch_merge_preflight(
  project,
  target_branch,
  source_branch,
  preview_id = optional reviewed preview,
  allow_uncovered_documents = false,
)
```

When `preview_id` is supplied, either branch advancing causes
`STALE_MERGE_PREVIEW`. A structural conflict causes `MERGE_CONFLICT` before any
compiler process starts.

## Response format

The response uses:

```text
weave-merge-preflight-v1
```

It contains:

- project and merge direction;
- common ancestor and exact target/source branch heads;
- exact `preview_id` and prospective merged-root hash;
- a bounded directional impact summary;
- the complete `weave-merge-validation-set-v1` result;
- `ready_for_publication`;
- `publication_tool` and exact `publication_arguments`.

## Directional impact

Preflight reports only consequences introduced by merging the source into the
current target. Work already present on the target branch is not reclassified as
incoming impact.

The embedded impact summary includes:

- changed program and target-metadata documents;
- candidate-covered and uncovered changed documents;
- target counts before and after the candidate;
- total affected and unaffected target counts;
- compact affected-target entries.

At most 200 affected target entries are returned. When more exist,
`impact_targets_truncated=true`, `impact.has_more=true`, and `impact.next_index`
identifies the continuation for `branch_merge_impact`.

Truncation affects only the human-facing impact list. The validation set still
uses the complete internal impact analysis and retains its separate compiler
fanout bound.

## Complete validation set

The embedded validation set checks every affected target that survives in the
candidate, in deterministic target-name order.

It reports:

- coverage result and uncovered-document policy;
- surviving affected targets and removed targets skipped;
- passed, failed, and unavailable targets;
- compact per-target compiler, source, diagnostic, and WIR evidence;
- deterministic `validation_set_id`;
- `ready_for_publication`.

Uncovered changed documents block by default before compiler startup. Setting
`allow_uncovered_documents=true` records an explicit review decision; it does not
claim those documents were validated.

## Preflight identity

The deterministic `preflight_id` binds:

```text
format
+ project and merge direction
+ preview ID and prospective merged-root hash
+ total and returned affected-target counts
+ impact truncation state
+ validation-set ID
+ uncovered-document policy
```

The same exact candidate, compiler identities, named-target graph, and policy
produce the same preflight identity.

## Publication

A ready response includes:

```json
{
  "publication_tool": "branch_merge",
  "publication_arguments": {
    "project": "demo",
    "target_branch": "main",
    "source_branch": "agent/feature",
    "preview_id": "...",
    "validate_affected_targets": true,
    "allow_uncovered_documents": false
  }
}
```

The normal agent workflow is:

```text
preflight = branch_merge_preflight(...)
review preflight
if preflight.ready_for_publication:
    call preflight.publication_tool with preflight.publication_arguments
```

The preflight result is evidence, not a bearer token. `branch_merge` repeats
impact analysis, coverage enforcement, and every affected-target frontend
validation. It then rechecks both branch heads inside the same SQLite write
transaction that publishes the immutable two-parent merge revision.

This closes both stale windows:

- a change before publication changes the preview ID and fails the replay;
- a change during or after validation fails the transactional head check.

## Failure visibility

Preflight returns an inspectable non-ready result for candidate coverage or
compiler failures rather than hiding the validation set.

Common states include:

- `ready_for_publication=true`: coverage and every affected target passed;
- `coverage_passed=false`: uncovered documents blocked validation before compiler
  startup;
- `failed_targets` non-empty: frontend validation rejected those targets;
- `unavailable_targets` non-empty: configured compiler validation was unavailable.

Publication converts those states to structured errors:

- `MERGE_UNCOVERED_DOCUMENTS`;
- `MERGE_VALIDATION_FAILED`;
- `MERGE_VALIDATION_UNAVAILABLE`;
- `STALE_MERGE_PREVIEW`;
- `MERGE_CONFLICT`.

Every failure leaves the target branch and audit tables unchanged.

## Compatibility and lower-level tools

The following tools remain public and useful for focused diagnosis:

- `branch_merge_preview` for structural conflicts and stable-node consequences;
- `branch_merge_impact` for paged target-graph analysis;
- `branch_merge_validate` for one named target;
- `branch_merge_validate_affected` for the complete validation set;
- `branch_merge` for publication.

Reviewed parallel-agent work should normally start with
`branch_merge_preflight`, not manually recreate the orchestration sequence.
