# Canonical project merge catalogs

Project merge orchestration uses one internal catalog service:
`ProjectMergeCatalogService`.

The service captures a deterministic lexical list of every branch head in one
project, identifies one exact target head, identifies every other branch as a
source, and computes the existing
`weave-project-merge-queue-catalog-v1` identifier.

## Shared consumers

The same service instance is owned by `ProjectMergeQueueService` and reused by:

- project merge queues;
- compiler-backed selected merge-preflight batches;
- selected in-memory merge-train previews.

This prevents those paths from independently rebuilding branch membership,
target/source partitioning, fanout checks, or catalog hashing.

## Compatibility

The refactor intentionally preserves:

- the stored catalog format string;
- lexical branch ordering;
- the maximum project branch fanout;
- every public MCP request and response shape;
- queue, selected-preflight, and merge-train error codes;
- stale-catalog behavior before and after expensive work;
- compiler, build, database, and Weave language protocols.

`PROJECT_MERGE_QUEUE_CATALOG_FORMAT` remains available as a compatibility alias
for the canonical format constant.

## Dependency rule

New project-level merge orchestration must receive or reuse a
`ProjectMergeCatalogService`. It must not query the `branches` table directly or
reconstruct the target/source/hash payload independently.

Callers remain responsible for their domain-specific stale and invalid-target
error codes. The catalog service accepts the invalid-target code so existing
public contracts stay stable while the capture algorithm remains centralized.
