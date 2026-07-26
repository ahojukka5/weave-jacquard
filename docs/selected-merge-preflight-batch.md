# Selected merge-preflight batches

## Purpose

Project merge and merge-impact queues provide cheap project-wide structural,
checkpoint, policy, and named-target coverage evidence. Running compiler-backed
preflight for every branch would defeat their bounded screening purpose and could
consume substantial compute without an explicit review decision.

`selected_merge_preflight_batch` is the explicit boundary between project-wide
screening and compiler-backed admission. The caller chooses a small source set
from one exact project merge catalog. Jacquard runs the normal authoritative
preflight independently for those sources and publishes no merge.

## Request

```text
selected_merge_preflight_batch(
  project,
  target_branch,
  sources,
  catalog_id,
  allow_uncovered_sources = optional,
  validation_result_limit = 20,
  document_limit = 100)
```

Required inputs are:

- one project and explicit target branch;
- one exact `catalog_id` returned by the project merge or merge-impact queue;
- a non-empty ordered list of 1–5 unique source branch names.

The tool does not discover, rank, expand, reorder, or prioritize the source list.

## Response format and identity

The response format is:

```text
weave-selected-merge-preflight-batch-v1
```

`batch_id` hashes the complete returned evidence, including:

- exact target and source catalog identity;
- selected source order;
- explicit uncovered-document override selection;
- compact compiler-backed results;
- per-source domain errors;
- public bounds and publication guidance.

Repeating the same batch against unchanged immutable evidence and deterministic
compiler behavior produces the same identity.

## Exact whole-project catalog

The batch recomputes the same catalog used by `project_merge_queue_page`:

- exact target branch and head revision;
- every source branch name and exact head revision, in lexical catalog order.

The supplied `catalog_id` must match before any compiler-backed work begins.
Otherwise the request returns:

```text
STALE_SELECTED_PREFLIGHT_CATALOG
```

After every selected source has completed or produced a per-source domain error,
Jacquard recomputes the complete catalog again. Any selected or unselected branch
addition, removal, or head advance invalidates the entire batch.

This final check matters because compiler validation can take long enough for
unrelated work to advance. Returning results under the old catalog would falsely
present them as one project-wide review moment.

Catalog staleness is a request-level error. No partial batch is returned.

## Explicit source selection

`sources` must contain 1–5 unique non-empty branch names. Every source must be a
non-target branch in the exact catalog.

Caller order is preserved in:

- execution;
- returned source entries;
- aggregate counts and evidence.

Caller order does not itself represent priority, urgency, age, quality, or
readiness. The tool merely respects the explicit order supplied.

Invalid selections return:

- `INVALID_SELECTED_PREFLIGHT_SOURCES` for malformed, duplicate, empty, or
  oversized selections;
- `INVALID_SELECTED_PREFLIGHT_SOURCE` when a named source is not a source member
  of the exact catalog;
- `INVALID_SELECTED_PREFLIGHT_TARGET` when the target branch is not in the
  catalog.

## Explicit uncovered-document overrides

`allow_uncovered_sources` is optional. When supplied, it must be a unique subset
of `sources`.

For a listed source, Jacquard invokes normal preflight with:

```text
allow_uncovered_documents = true
```

For every other selected source, the value is false.

This input expresses only the caller's explicit request. The exact target policy
remains authoritative. If the target forbids uncovered-document overrides, that
source returns a normal policy error entry.

Invalid override lists return:

```text
INVALID_SELECTED_PREFLIGHT_OVERRIDES
```

## Compiler-backed execution

For every selected source, Jacquard:

1. recomputes the exact target/source merge preview;
2. verifies the preview heads against the catalog;
3. invokes the existing one-call `branch_merge_preflight` service with the exact
   preview ID and explicit uncovered override choice;
4. compacts the result into bounded batch evidence.

Normal preflight remains authoritative. It composes:

- structural merge preview;
- target and source policy context;
- named-target impact and coverage;
- affected-target compiler validation;
- publication guard identity.

The batch adds orchestration and compact aggregation only. It does not introduce
a second compiler or admission algorithm.

## Independent per-source outcomes

A selected source returns either:

```text
status = "completed"
```

or:

```text
status = "error"
```

A completed source can be:

- `ready_for_publication = true`;
- `ready_for_publication = false` because validation, coverage, or another
  preflight gate did not pass.

A source-level domain error is captured in that source entry. Typical examples
include:

- stable-ID merge conflict;
- target policy violation;
- missing target or revision evidence;
- unavailable or malformed compiler/preflight evidence.

One source's domain error does not stop later selected sources. This permits one
batch to return ready, failed-validation, conflict, and policy-error entries
side by side.

Catalog-staleness errors are different: they invalidate the shared batch identity
and therefore abort the request.

## Compact completed entries

A completed source entry reports:

- exact source head and preview identity;
- base revision and prospective merged root hash;
- `preflight_id` and `ready_for_publication`;
- changed and uncovered program-document totals;
- bounded changed and uncovered document names with truncation;
- affected-target and coverage counts;
- validated, passed, failed, and unavailable target counts;
- bounded target-name lists;
- bounded target-validation records;
- exact target/source policy summaries and source-policy-ignore evidence;
- normal publication tool and guarded publication arguments;
- a replayable full-preflight call.

A compact target-validation record contains:

- target name and `validation_id`;
- compiler availability and validity;
- return code and timeout state;
- bounded diagnostic;
- compiler SHA-256;
- WIR SHA-256 and byte count when available.

## Compact error entries

An error source entry retains:

- exact source head and preview ID;
- explicit uncovered override choice;
- structured error code and message;
- conflict list when relevant;
- a replayable full-preflight call;
- `ready_for_publication = false`.

The caller can inspect or replay that one source independently after correcting
its underlying problem and obtaining a fresh catalog.

## Public bounds

Maximums are:

- five selected source branches;
- 64 returned target-validation records and target-name results per source;
- 200 returned changed or uncovered document names per source.

`validation_result_limit` bounds:

- target-validation records;
- passed target names;
- failed target names;
- unavailable target names.

`document_limit` independently bounds changed and uncovered program-document
names.

Complete counts and truncation flags preserve omitted evidence. The full normal
preflight can be replayed through `full_preflight` when more detail is required.

Invalid bounds return:

```text
INVALID_SELECTED_PREFLIGHT_LIMIT
```

## Whole-catalog concurrency during compiler work

Before each source preflight, the exact preview is checked against the selected
catalog heads. A stale preview becomes:

```text
STALE_SELECTED_PREFLIGHT_CATALOG
```

After all selected work, the complete catalog is checked again. This includes
branches that were not selected for compilation.

The batch therefore guarantees that a successful response belongs to one exact
project branch-head catalog before and after compiler execution. It does not lock
branches while compilation runs; it detects and rejects catalog drift.

## Aggregate counts

The top-level response reports:

- selected source count;
- completed source count;
- error source count;
- ready source count;
- completed-but-not-ready source count.

These counts summarize evidence only. They do not rank candidates or authorize
publication.

## Publication boundary

The batch creates no merge revision and advances no branch.

For a completed ready source, use:

```text
publication_tool
publication_arguments
```

These are the guarded arguments returned by normal preflight. Calling
`branch_merge` with them rechecks:

- exact preview identity;
- exact preflight identity;
- target policy;
- compiler validation requirements;
- source and target branch heads.

`ready_for_publication = true` is exact preflight evidence, not an automatic
publication action or permanent guarantee. Branch heads can change immediately
after the batch returns.

## Read-only persistent behavior

The batch can run compiler processes and create transient compiler work files,
but it creates no Jacquard:

- branch or revision;
- operation row;
- context or checkpoint document;
- revision-document link;
- merge publication.

Normal compiler validation may produce only the existing transient or cached
artifacts governed by its own contract. The batch adds no stored protocol.

## Errors

Request-level errors include:

- `INVALID_SELECTED_PREFLIGHT_CATALOG` for a malformed catalog ID;
- `STALE_SELECTED_PREFLIGHT_CATALOG` for catalog mismatch before, during, or
  after compiler work;
- `INVALID_SELECTED_PREFLIGHT_TARGET`;
- `INVALID_SELECTED_PREFLIGHT_SOURCE`;
- `INVALID_SELECTED_PREFLIGHT_SOURCES`;
- `INVALID_SELECTED_PREFLIGHT_OVERRIDES`;
- `INVALID_SELECTED_PREFLIGHT_LIMIT`;
- normal project and branch not-found errors;
- structural queue branch-fanout errors.

Per-source domain errors are returned inside the successful batch response when
the shared catalog remains valid.

## Qualification

Direct tests prove:

- deterministic batch identity;
- caller-order preservation;
- mixed ready, not-ready, conflict, and policy-error outcomes;
- independent continuation after per-source errors;
- explicit uncovered override selection;
- bounded compiler and document evidence;
- guarded publication arguments and replayable full-preflight calls;
- stale catalog rejection before execution;
- complete catalog recheck after compiler work, including an unselected branch;
- source, override, catalog, and bound validation;
- shared production queue and preflight construction.

The production stdio lifecycle uses a controlled public `weavec --frontend`
protocol to produce:

- one passing affected target;
- one deterministic frontend validation failure;
- one stable-ID conflict;
- one target-policy violation for a forbidden uncovered override.

All four outcomes are returned in one batch. The lifecycle proves branch heads
remain unchanged, an unselected branch advance invalidates the old catalog, and
no merge revision or batch operation row is published.

Standard CI retains `selected-merge-preflight-batch-trace.json`. The packaged
`weavec` workflow verifies that final MCP registration does not regress native
builds, merge publication, policy, one-call preflight, checkpoints, resume,
timeline, project status, merge queues, impact queues, or artifact discovery.

## Compatibility

The feature is additive and reuses existing project merge catalogs, merge
previews, merge impact, policies, validation sets, compiler validation, and
preflight/publication contracts.

It changes no database schema, stored protocol, compiler interface, build key,
manifest, node ID, or Weave language rule.
