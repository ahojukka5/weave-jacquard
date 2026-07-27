# Revision evidence graphs

## Purpose

`revision_evidence_page` recovers retained build and behavioral evidence for one
exact immutable project revision when an agent no longer has the individual
artifact IDs in context.

The tool is revision-centered and read-only. It returns a bounded typed graph,
not a mutable catalog or a claim that all relevant checks were retained.

## Supported evidence kinds

One request selects exactly one kind:

- `build`: committed-revision compiler builds;
- `test_run`: individual sandboxed behavioral runs;
- `test_batch`: explicit ordered behavioral test batches;
- `tested_merge_attestation`: state-identity attestations linking a committed
  merge revision to its retained virtual-candidate qualification.

Virtual-candidate qualifications and candidate builds are reached only through a
verified tested-merge attestation. They are never presented as committed-revision
builds or ordinary revision-bound test batches.

## Public request

```text
revision_evidence_page(
  project,
  revision_id,
  kind,
  start_after_id = null,
  catalog_id = null,
  limit = 25,
  scan_limit = 100)
```

`revision_id` must belong to `project`. The selected revision is immutable, so the
subject node and every revision field remain stable across pages.

## Nodes and edges

Every page includes the subject revision node:

```text
revision:<revision_id>
```

Additional node kinds include:

- `build`;
- `test_run`;
- `test_batch`;
- `tested_merge_attestation`;
- `merge_candidate_qualification`;
- `merge_candidate_build`.

Typed edges currently include:

```text
build                     --built_from_revision--> revision
test_run                  --executed_revision----> revision
test_run                  --used_build-----------> build
test_batch                --qualified_revision---> revision
test_batch                --contains_run---------> test_run
tested_merge_attestation  --attests_revision_state--> revision
tested_merge_attestation  --binds_qualification----> merge_candidate_qualification
merge_candidate_qualification --used_candidate_build--> merge_candidate_build
```

An edge may refer to a typed node that is discoverable from another evidence-kind
page. For example, a `test_run` page can refer to a `build` node without embedding
the complete verified build manifest. Follow the node's `detail.tool` and
`detail.arguments`, or page the referenced evidence kind, for the full verified
artifact.

## Verification boundary

The graph service does not implement a second artifact parser. Every returned
member passes the existing authoritative admission path for its store:

- `build_get` verification for builds;
- `test_run_get` verification for individual runs;
- `test_batch_get` verification for batches;
- `tested_merge_attestation_get` plus candidate-qualification verification for
  attestations.

This preserves each artifact format's existing path-containment, regular-file,
hash, identity, subject, compiler, sandbox, and subordinate-evidence checks.

Malformed or corrupt catalog members are returned only in `rejected` as:

```text
{
  evidence_id,
  error_code
}
```

Raw exception text, absolute artifact paths, compiler output, and server-local
storage locations are never included in the graph response.

## Catalog membership

Each evidence kind has a live filesystem-backed catalog. Membership requires:

- a direct child directory of the configured store root;
- a 32-character lowercase hexadecimal evidence ID;
- no symlink at the evidence-directory boundary;
- the expected regular non-symlink manifest file.

The content-derived `catalog_id` binds:

- project;
- exact revision;
- evidence kind;
- the complete lexically ordered live membership list.

Replaying `catalog_id` across pages rejects additions or removals with
`STALE_REVISION_EVIDENCE_CATALOG`.

Omitting `catalog_id` intentionally accepts the current live membership on each
request.

## Pagination and sparse stores

`limit` bounds matching evidence returned. `scan_limit` independently bounds how
many catalog members may be verified in one request.

```text
1 <= limit <= 100
1 <= scan_limit <= 200
scan_limit >= limit
```

The two bounds are separate because a store may contain:

- valid evidence from other projects;
- valid evidence for other revisions;
- corrupt members;
- matching evidence for the requested revision.

A page can therefore be sparse or empty while still advancing
`next_after_id`. The continuation is the last lexically scanned evidence ID, not
the last matching result.

`start_after_id` uses lexical insertion semantics. It does not need to remain a
current catalog member when the caller intentionally omits `catalog_id`; replaying
a stable catalog remains the preferred multi-page workflow.

## Result identity

The page format is `weave-revision-evidence-page-v1`.

`page_id` binds the exact response, including:

- revision subject;
- kind and catalog identity;
- limits and cursor;
- nodes and edges;
- rejected IDs and error codes;
- interpretation flags.

The page identity is evidence of one exact discovery response. It is not a bearer
token and grants no artifact access beyond the ordinary detail tools.

## Honest interpretation boundary

Revision evidence graphs cover retained artifacts only.

They do **not** claim:

- complete behavioral or compiler coverage;
- that an absent check never ran;
- that every relevant artifact was retained;
- persistence of merge preview or preflight responses;
- target-branch policy admission;
- human review or approval;
- merge or release readiness.

Merge previews and preflights remain intentionally non-persistent. A tested-merge
attestation proves only that a committed two-parent merge state matches the exact
virtual candidate represented by its retained qualification; failed or incomplete
qualification status remains failed or incomplete.

## Failure and mutation semantics

Evidence graph reads:

- create no revision;
- move no branch;
- create no build or test artifact;
- change no catalog membership;
- reveal no server-local path.

Invalid project/revision, kind, bounds, cursor, catalog identity, or unavailable
catalog access returns a structured error and no partial graph page.
