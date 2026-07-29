# Revision-wide resource limits

Jacquard treats complete immutable revision state, revision ancestry, and
agent-facing presentation as bounded resources. A caller must never receive a
plausible partial merge base, revision identity, compiler input set, qualification
result, or workflow summary after an internal completeness limit is exceeded.

The active ceilings are collected in `weave_frontend.revision_limits` and exposed
through `REVISION_RESOURCE_LIMITS` for deterministic inspection and tests. Services
that retain compatibility constants are covered by synchronization tests so their
public bounds cannot drift from the catalog silently.

## Current ceilings

### Complete internal work

| Dimension | Maximum |
|---|---:|
| compressed bytes in one retained snapshot | 16 MiB |
| decoded bytes in one retained snapshot | 32 MiB |
| modules in one immutable revision | 4,096 |
| aggregate decoded snapshot bytes in one revision | 256 MiB |
| UTF-8 bytes in one qualified module name | 4,096 |
| source documents in one compiler invocation or production build target | 256 |
| revision-DAG nodes admitted by one ancestry operation | 65,536 |
| revision-DAG edges admitted by one ancestry operation | 131,072 |
| first-parent revisions admitted by branch activity summary or reachability | 65,536 |
| revisions scanned by one checkpoint timeline or branch status lookup | 500 |
| branches admitted by one agent-status catalog | 1,000 |
| surviving targets validated by one preflight | 64 |

### Agent-facing presentation

| Dimension | Maximum |
|---|---:|
| branch-history rows per page | 200 |
| operation rows per page | 200 |
| checkpoint timeline rows per page | 50 |
| agent-status branches per page | 100 |
| stable-node search results | 500 |
| node inspection depth | 64 |
| revision-diff rows per page | 200 |
| merge-impact targets per page | 200 |
| merge-queue sources per page | 20 |
| merge-impact-queue sources per page | 10 |
| selected merge-train sources | 10 |
| selected preflight sources | 5 |
| conflicts presented per queued source | 100 |
| changed documents presented per queued source | 200 |
| coverage documents presented per impact-queue source | 200 |
| documents presented per selected preflight source | 200 |
| preflight impact targets presented | 200 |
| resume program documents | 200 |
| resume build targets | 100 |
| resume additional sources per target | 200 |
| resume test targets | 100 |
| resume task contracts | 100 |
| resume context documents | 100 |
| resume branches | 200 |
| resume first-parent history rows | 50 |
| resume operation rows | 200 |

Exact-limit inputs are admitted. Limit-plus-one inputs fail with a stable domain
error before an incomplete result is treated as valid. Booleans are rejected even
though Python otherwise treats them as integers.

## Revision state

The snapshot codec enforces module-count and aggregate decoded-byte limits while it
reconstructs a complete revision. The root hash is checked only after every admitted
module has decoded and passed structural and AST-hash verification. Overflow returns
`REVISION_MODULE_LIMIT_EXCEEDED` or `REVISION_DECODED_LIMIT_EXCEEDED`; it never
returns a partial module mapping or root identity.

## Compiler document fanout

One build, validation, candidate build, or target-driven compiler invocation may
select at most 256 unique source documents. The shared compiler input boundary
rejects larger sets with `BUILD_DOCUMENT_LIMIT_EXCEEDED` before source rendering,
materialization, cache-key construction, or compiler execution.

The race-safe production build-target registry applies the same ceiling when a
target is written or parsed. A retained target cannot bypass the compiler boundary
by encoding an oversized `source` field set. Caller-supplied source order remains
authoritative; Jacquard does not silently omit, reorder, rank, or discover sources.

## Revision-DAG analysis

Merge-base selection uses one bounded analysis of the union ancestry graph for both
reviewed heads. Each admitted revision row is fetched once. Each stored parent edge
is counted once and propagated for at most the two input sides.

The analysis derives all best common ancestors in one deterministic
descendant-to-ancestor topological pass. It does not launch a fresh ancestry walk
for every common ancestor. Criss-cross histories therefore produce a stable lexical
set of best common ancestors and preserve the existing conflict rule when that set
contains more than one revision.

Failures are explicit:

- `REVISION_DAG_NODE_LIMIT_EXCEEDED` when the next revision would exceed the node
  ceiling;
- `REVISION_DAG_EDGE_LIMIT_EXCEEDED` when parent edges exceed the edge ceiling;
- `REVISION_DAG_CYCLE` when ancestry is not acyclic;
- a not-found error for a dangling revision reference;
- the existing merge conflict when no common ancestor or multiple best common
  ancestors exist.

The merge-preview ID binds the analysis format, both reviewed heads, every best
common ancestor, visited node and edge counts, and the effective graph ceilings.
Changing those limits invalidates old preview evidence. Successful merge operation
audit payloads retain the same ancestry evidence.

## Bounded branch and checkpoint activity

First-parent history pages inspect at most the requested page plus one continuation
row. Reachability checks and complete activity summaries admit at most 65,536
revisions. A longer history fails with `BRANCH_HISTORY_SCAN_LIMIT_EXCEEDED` or
`BRANCH_ACTIVITY_REVISION_LIMIT_EXCEEDED`; it is not reported as a complete summary.
A first-parent cycle fails with `REVISION_HISTORY_CYCLE`.

Complete activity summaries report `complete=true`, `truncated=false`, and the
internal revision ceiling. History and operation pages report their requested limit,
maximum page size, returned count, truncation state, and continuation cursor.

Checkpoint timelines, project agent-status pages, and queue checkpoint orientation
already validate independent page and first-parent scan bounds. Their active values
are now part of the central resource catalog, with synchronization tests preserving
the existing public constants and response formats.

## Node reads, diff, and impact

`node_find` traverses the complete structurally admitted document once, counts every
match, and retains only the requested prefix. Parent and position metadata are
collected during the same traversal rather than by repeatedly searching from the
root. The response distinguishes `total_match_count` from `returned_count` and
reports `truncated` explicitly.

`node_inspect` accepts depths from zero through 64. Negative depths are no longer
silently coerced to zero.

Revision-diff and merge-impact pages validate both their non-negative start index
and bounded page size. They report the complete change or affected-target count,
returned count, truncation state, continuation index, and maximum page size.
Internal qualification paths continue to use the complete impact analysis rather
than a presented prefix.

## Queues, resume, and preflight

Project merge queues and merge-impact queues validate every public limit, including
page size, checkpoint scan, conflicts, changed documents, affected targets, and
coverage documents. Their `page_id` hashes the complete response, so requested
limits, effective ceilings, and truncation flags are identity-bound.

Selected merge-train and selected preflight operations also validate their source,
document, conflict, and validation-result bounds. These values are included in the
central catalog and checked against the compatibility constants used by their
existing public services.

Resume snapshots separate complete counts from returned prefixes for programs,
targets, target sources, test targets, task contracts, contexts, branches, history,
and operations. Requested limits are included in `snapshot_id`; invalid or oversized
values fail with `INVALID_RESUME_SNAPSHOT_LIMIT`.

Preflight validates the complete affected-target set independently of its bounded
impact presentation. `preflight_id` now binds the effective impact presentation
ceiling as well as total count, returned count, and truncation state. Changing the
ceiling therefore invalidates stale preflight evidence without changing the
qualification decision.

## Failure versus presentation truncation

Internal completeness limits fail closed. They do not set a `truncated` flag and
continue with partial data.

Presentation limits may return a complete deterministic prefix only when omitted
rows do not alter the operation's internal qualification or identity claim. Such
responses expose:

- the requested limit;
- the maximum supported limit;
- complete and returned counts where available;
- `truncated` or an equivalent field;
- an explicit continuation cursor when the interface supports continuation.

The final public `branch_history` registration returns bounded metadata instead of
an ambiguous bare revision list. `branch_history_page` remains the preferred
continuation-oriented history API, while the internal `list_history` compatibility
method returns only the bounded revision prefix for legacy Python callers.
