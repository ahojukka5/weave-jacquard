# Project merge-impact queues

## Purpose

`project_merge_queue_page` answers whether exact source and target branch heads
compose structurally. A reviewer often needs one additional layer before deciding
which clean candidates deserve compiler-backed preflight:

- which program documents changed;
- whether named build targets cover those documents;
- which targets are affected;
- whether the exact target policy permits uncovered-document overrides;
- whether a source branch advertises a different policy.

`project_merge_impact_queue_page` composes that evidence over the same exact
branch-head catalog without running a compiler or publishing a merge.

## Request

```text
project_merge_impact_queue_page(
  project,
  target_branch = "main",
  start_after_source = optional,
  catalog_id = optional,
  limit = 5,
  checkpoint_scan_limit = 100,
  conflict_limit = 20,
  changed_document_limit = 50,
  affected_target_limit = 50,
  coverage_document_limit = 100)
```

The target branch must exist. Every other branch in the exact catalog is a source
candidate.

## Format and deterministic identity

The response format is:

```text
weave-project-merge-impact-queue-v1
```

The underlying structural queue establishes:

- exact target head;
- exact source heads;
- lexical source ordering;
- stable `catalog_id`;
- exclusive `next_after_source` continuation;
- structural preview identities.

The impact response exposes the underlying `queue_page_id` and computes its own
`page_id` over all returned structural, policy, coverage, checkpoint, bound, and
continuation evidence.

Repeating a request against unchanged stored evidence produces the same IDs.

## Stable catalog continuation

Continuation follows the structural queue contract:

```text
start_after_source = previous next_after_source
catalog_id = previous catalog_id
```

If the target or any source branch is added, removed, or advances, the request
returns:

```text
STALE_PROJECT_MERGE_QUEUE_CATALOG
```

The same error is returned when a head changes between structural preview and
impact composition. No partial page is returned and Jacquard never combines
coverage evidence from different branch-head sets.

## Structural conflict short-circuit

A structurally conflicted source returns:

- `impact_classification = "conflicted"`;
- `impact = null`;
- `coverage_gate = null`;
- `impact_call = null`;
- normal compact conflict and source-checkpoint evidence;
- `preflight = null`.

The impact service is not called for a conflicted source. Named-target coverage
is undefined until the stable-ID merge conflict is resolved.

## Clean impact classifications

Every structurally clean source receives one non-compiling classification.

### `covered_program_changes`

One or more ordinary program documents changed and every changed program document
is referenced by at least one named target in the prospective merged state.

This means named-target coverage exists. It does not mean those targets compile.

### `uncovered_program_changes`

One or more changed program documents are not referenced by any named target in
the prospective merged state.

The response lists bounded uncovered-document evidence and reports how the exact
target policy treats uncovered overrides.

### `target_definition_changes_only`

No ordinary program document changed, but one or more reserved build-target
definition documents changed.

Affected target evidence explains added, removed, or modified definitions.

### `no_changes`

The exact structural merge candidate changes neither ordinary program documents
nor build-target definitions relative to the target head.

A no-change candidate is structurally mergeable but may not need publication.
The tool does not make that decision.

## Exact policy authority

`target_merge_policy` is resolved by calling the revisioned policy registry with
the exact target catalog revision, not a later mutable branch head.

Every source entry contains:

```text
merge_policy.target
merge_policy.source
merge_policy.source_policy_ignored
```

The source policy is resolved at the exact source catalog revision.

The target policy is authoritative for merge admission. A source policy is
visible for review but cannot weaken target requirements. In particular, a source
that allows uncovered documents cannot override a target that forbids them.

`source_policy_ignored` reports whether the normalized source and target policy
hashes differ. It does not imply either policy is better or newer.

## Coverage gate evidence

For each clean source, `coverage_gate` reports:

- `uncovered_documents_present`;
- `target_allows_uncovered_documents`;
- `override_possible`.

`override_possible` is true only when uncovered documents exist and the exact
target policy permits an override.

This is structural policy evidence, not permission to publish automatically. A
caller must still make the override choice explicitly through normal preflight
and only under the target policy.

## Compact impact evidence

Each clean `impact` includes:

- existing merge-impact format and preview identity;
- merged root hash;
- changed program-document total, bounded names, and truncation;
- changed target-definition total, bounded names, and truncation;
- covered changed-document total, bounded names, and truncation;
- uncovered changed-document total, bounded names, and truncation;
- target counts before and after;
- total affected and unaffected target counts;
- bounded affected-target entries;
- affected-target truncation and next index.

Affected-target entries retain the existing impact contract:

- target name and added/removed/modified/unchanged status;
- affected reasons;
- changed source documents;
- before and after target definitions.

Use the replayable impact call for additional affected-target pages when the
compact queue truncates them.

## Public bounds

Maximums are:

- 10 source entries per page;
- 500 first-parent revisions scanned for checkpoint evidence per source;
- 100 returned conflict strings per source;
- 200 returned structural changed-document names per source;
- 200 returned affected named targets per source;
- 200 returned names in each coverage-document collection per source.

Every compact collection reports a complete total and explicit truncation.
Affected targets additionally report `next_affected_target_index`.

Invalid bounds return:

```text
INVALID_PROJECT_MERGE_IMPACT_QUEUE_LIMIT
```

The underlying structural queue continues to enforce its 1,000-branch catalog
maximum.

## Replayable follow-up calls

The structural queue calls remain present:

- `full_preview` for complete node/document preview evidence;
- `preflight` for structurally mergeable candidates.

Every clean impact entry additionally contains:

```text
impact_call.tool = branch_merge_impact
impact_call.arguments = {
  project,
  target_branch,
  source_branch,
  preview_id,
  start_index = 0,
  limit = affected_target_limit
}
```

The call is bound to the exact structural `preview_id`. It can be replayed to
recover the normal complete impact-page contract and continued using its
`next_index`.

Conflicted sources return no impact or preflight call.

## No compiler execution

`project_merge_impact_queue_page` does not run:

- `weavec`;
- named-target builds;
- affected-target validation;
- merge preflight;
- merge publication.

The tool can therefore screen many source branches cheaply while still exposing
which clean candidates need target validation.

Coverage and policy evidence do not prove:

- compiler correctness;
- successful affected-target builds;
- preflight identity;
- unchanged source and target heads at publication;
- human approval;
- priority or merge readiness.

Run `branch_merge_preflight` before publication whenever required by target
policy or workflow. Publication must retain the normal preview/preflight and
compare-and-set head checks.

## Source checkpoint context

The complete compact `source_checkpoint` evidence from the structural queue is
preserved for every source:

- checkpoint state and exact lag when known;
- bounded first-parent scan evidence;
- verified checkpoint identity, status, objective, and counts;
- program-root drift since checkpoint.

Checkpoint context does not affect source ordering, target policy authority, or
coverage classification.

## Ordering is not priority

Sources remain lexically ordered for deterministic paging. This is not a ranking
by:

- urgency or age;
- amount or quality of work;
- checkpoint freshness;
- coverage completeness;
- policy compatibility;
- compiler or merge readiness.

Consumers must select follow-up work using explicit project goals and the
returned evidence.

## Read-only behavior

The tool creates no:

- branch or revision;
- operation row;
- document or revision-document link;
- build or compiler artifact;
- filesystem output;
- merge publication.

It reads committed immutable state and composes existing deterministic services.

## Errors

The service preserves normal structural queue errors, including invalid target,
cursor, catalog, branch fanout, and stale catalog.

Additional failures include:

- `INVALID_PROJECT_MERGE_IMPACT_QUEUE_LIMIT` for invalid new bounds;
- normal merge-impact validation errors for malformed target definitions;
- normal policy verification errors for malformed or tampered exact-revision
  policy evidence;
- normal checkpoint verification errors for malformed or tampered checkpoint
  evidence.

A stale impact preview is translated to the stable queue-level stale-catalog
error.

## Qualification

Direct tests prove:

- deterministic queue and page identities;
- structural conflict short-circuiting before impact analysis;
- covered, uncovered, target-definition-only, and no-change classifications;
- exact target and source policy resolution;
- source-policy visibility without target-policy authority;
- bounded program, target-definition, covered, uncovered, and affected-target
  evidence;
- exact affected-target continuation;
- coverage-gate semantics;
- source checkpoint context;
- stale-catalog rejection;
- every public bound;
- shared production service construction.

The production stdio lifecycle builds all five classes, replays one returned
`branch_merge_impact` call, confirms no compiler configuration is present,
verifies queue reads preserve branch heads, rejects an old catalog after a source
advance, and proves no merge revision or impact-queue operation was published.

Standard CI retains `project-merge-impact-queue-trace.json`. The packaged
`weavec` workflow verifies that final MCP registration does not regress native
builds, merge publication, policy, preflight, checkpoint, resume, timeline,
comparison, project status, structural merge queues, or artifact discovery.

## Compatibility

The feature is additive and read-only. It reuses existing branch-head catalogs,
merge preview, merge impact, merge policy, named-target, checkpoint, and revision
formats.

It changes no database schema, stored format, compiler protocol, build key,
manifest, node ID, or Weave language rule.
