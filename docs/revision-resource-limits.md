# Revision-wide resource limits

Jacquard treats complete immutable revision state and revision ancestry as bounded
resources. A caller must never receive a plausible partial merge base, revision
identity, compiler input set, or qualification result after an internal completeness
limit is exceeded.

The limits enforced by this slice are centralized in
`weave_frontend.revision_limits`.

## Current ceilings

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
| first-parent history rows returned by the compatibility page | 200 |

Exact-limit inputs are admitted. Limit-plus-one inputs fail with a stable domain
error before an incomplete result is treated as valid.

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
by encoding an oversized `source` field set.

The caller-supplied order remains authoritative. The limit does not discover,
reorder, rank, or silently omit documents.

## Revision-DAG analysis

Merge-base selection uses one bounded analysis of the union ancestry graph for both
reviewed heads. Each admitted revision row is fetched once. Each stored parent edge
is counted once and propagated for at most the two input sides.

The analysis then derives all best common ancestors in one deterministic
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

## Failure versus presentation truncation

Internal completeness limits fail closed. They do not set a `truncated` flag and
continue with partial data.

Presentation limits may return a complete prefix when the operation's identity and
qualification decision do not depend on the omitted rows. The bounded history result
reports:

- `returned_count`;
- the effective `limit`;
- `truncated`;
- `next_revision_id`;
- the maximum supported page size.

The final public `branch_history` registration now returns that evidence object
instead of an ambiguous bare revision list. The continuation-oriented
`branch_history_page` remains available for explicit first-parent paging. The
internal `list_history` compatibility method returns only the bounded `revisions`
prefix for legacy Python callers.

## Remaining issue #105 work

This first slice bounds revision-DAG analysis, public and compatibility first-parent
history, complete revision loading, compiler document fanout, and production target
fanout. The follow-up slice will centralize and verify the remaining public limits
for branch activity summaries, node search and inspection, revision diff, impact and
queue pages, resume reads, and preflight responses. It will also bind relevant
effective limits into deterministic evidence identities where those identities
depend on complete internal results.
