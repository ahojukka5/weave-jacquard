# One-call merge preflight

## Purpose

`branch_merge_preflight` is the default review entrypoint for combining
independent Jacquard branches. It composes all non-mutating admission layers into
one bounded deterministic result:

```text
target-authoritative merge policy
+ visible source-branch policy
+ stable-ID merge preview
+ directional named-target impact
+ candidate coverage analysis
+ complete affected-target frontend validation
= merge preflight evidence
```

The tool creates no revision, branch update, audit row, retained compiler output,
or build artifact.

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

A supplied stale preview returns `STALE_MERGE_PREVIEW`. A structural conflict
returns `MERGE_CONFLICT` before compiler startup.

## Policy resolution

Preflight first resolves effective first-parent policies for both branches.

- `target_merge_policy` is authoritative;
- `source_merge_policy` is review evidence;
- `source_policy_ignored=true` reports different hashes;
- the incoming source policy cannot weaken target admission.

The target policy may:

- require exact preflight replay;
- require all affected surviving targets to validate;
- forbid uncovered-document overrides;
- set an affected-target validation ceiling below the global maximum.

A forbidden override returns `MERGE_POLICY_VIOLATION` before impact or compiler
work. A target ceiling violation returns `TOO_MANY_AFFECTED_TARGETS` before
compiler startup.

See [`merge-policy.md`](merge-policy.md).

## Response format

The response uses:

```text
weave-merge-preflight-v1
```

It contains:

- project and merge direction;
- common ancestor and exact target/source heads;
- `target_merge_policy` and `source_merge_policy`;
- `source_policy_ignored`;
- exact `preview_id` and prospective merged-root hash;
- bounded directional impact summary;
- complete `weave-merge-validation-set-v1`;
- `ready_for_publication`;
- `publication_tool` and exact `publication_arguments`.

## Directional impact

Preflight reports only consequences introduced by merging the source into the
current target. Existing target-side work is not reclassified as incoming
impact.

The embedded summary includes:

- changed program and target-metadata documents;
- candidate-covered and uncovered changed documents;
- target counts before and after;
- affected and unaffected target counts;
- compact affected-target entries.

At most 200 entries are returned. More entries set
`impact_targets_truncated=true`, `impact.has_more=true`, and an explicit
`impact.next_index` for `branch_merge_impact` continuation.

Truncation is presentation-only. Complete internal impact still drives the
validation set.

## Complete validation set

The embedded set validates every affected target surviving in the candidate, in
deterministic target-name order. It reports:

- effective target validation ceiling;
- coverage and uncovered-document policy;
- surviving affected and skipped removed targets;
- passed, failed, and unavailable targets;
- compact compiler/source/diagnostic/WIR evidence;
- deterministic `validation_set_id`;
- `ready_for_publication`.

Uncovered documents block before compiler startup unless both target policy and
request allow the explicit override. The override records acceptance of the gap;
it does not claim validation.

## Preflight identity

The deterministic `preflight_id` binds:

```text
format
+ project and merge direction
+ preview and merged-root identity
+ total and returned impact counts
+ impact truncation state
+ validation-set identity
+ uncovered-document policy
+ target policy hash
+ source policy hash
+ source-policy-ignored disposition
```

The same exact branches, policies, compiler identities, target graph, source
hashes, and request policy produce the same preflight ID.

A target policy revision or a source policy revision changes preflight identity,
even when program trees are otherwise unchanged.

## Publication

A policy-aware ready response includes:

```json
{
  "publication_tool": "branch_merge",
  "publication_arguments": {
    "project": "demo",
    "target_branch": "main",
    "source_branch": "agent/feature",
    "preview_id": "...",
    "validate_affected_targets": true,
    "allow_uncovered_documents": false,
    "preflight_id": "..."
  }
}
```

Normal workflow:

```text
preflight = branch_merge_preflight(...)
review policy, impact, coverage, and validation evidence
if preflight.ready_for_publication:
    call preflight.publication_tool with preflight.publication_arguments
```

Preflight is evidence, not a bearer token. Publication:

1. resolves current target and source policies;
2. recomputes policy-aware preflight against current heads;
3. compares exact `preflight_id`;
4. enforces complete validation-set readiness;
5. publishes using the validated preview ID;
6. rechecks both heads inside the SQLite write transaction.

The recomputed validation set is reused. Jacquard does not launch a redundant
second compiler fanout before the same transactional head check.

Stale windows are closed because:

- any branch or policy change before publication changes preflight identity;
- any change during or after validation fails the transactional head check.

## Failure visibility

Preflight returns inspectable non-ready evidence for coverage or compiler
failures. Common states:

- `ready_for_publication=true`: policy, coverage, and every selected target pass;
- `coverage_passed=false`: uncovered documents blocked compiler startup;
- `failed_targets` non-empty: frontend rejected those targets;
- `unavailable_targets` non-empty: compiler validation was unavailable.

Policy/preflight calls may also return:

- `MERGE_POLICY_VIOLATION`;
- `TOO_MANY_AFFECTED_TARGETS`;
- `STALE_MERGE_PREVIEW`;
- `MERGE_CONFLICT`.

Publication may additionally return:

- `MERGE_POLICY_PREFLIGHT_REQUIRED`;
- `MERGE_POLICY_AFFECTED_VALIDATION_REQUIRED`;
- `STALE_MERGE_PREFLIGHT`;
- `MERGE_UNCOVERED_DOCUMENTS`;
- `MERGE_VALIDATION_FAILED`;
- `MERGE_VALIDATION_UNAVAILABLE`.

Every failure leaves target branch and audit tables unchanged.

## Compatibility and diagnostic layers

When target policy is unconfigured, existing direct and validation-gated merge
calls remain compatible. The following lower-level tools remain useful for
focused diagnosis:

- `merge_policy_get` for historical admission rules;
- `branch_merge_preview` for conflicts and stable-node consequences;
- `branch_merge_impact` for paged target-graph analysis;
- `branch_merge_validate` for one target;
- `branch_merge_validate_affected` for the complete validation set;
- `branch_merge` for policy-permitted publication.

Reviewed parallel-agent work should normally begin with
`branch_merge_preflight`, not manually recreate the orchestration sequence.
