"""Bounded deterministic analysis of immutable revision ancestry graphs."""

from __future__ import annotations

import heapq
import sqlite3
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .errors import ConflictError, NotFoundError, ValidationError
from .revision_limits import MAX_REVISION_DAG_EDGES, MAX_REVISION_DAG_NODES

REVISION_DAG_ANALYSIS_FORMAT = "weave-revision-dag-analysis-v1"
_LEFT = 1
_RIGHT = 2
_BOTH = _LEFT | _RIGHT
ParentLoader = Callable[[str], tuple[str | None, str | None]]
ParentSource = sqlite3.Connection | ParentLoader


@dataclass(frozen=True)
class RevisionDagAnalysis:
    """Complete bounded ancestry evidence for two immutable revisions."""

    left_revision_id: str
    right_revision_id: str
    best_common_ancestors: tuple[str, ...]
    common_ancestor_count: int
    nodes_visited: int
    edges_visited: int
    max_nodes: int
    max_edges: int

    def require_single_best(self) -> str:
        """Return the unique best common ancestor or preserve merge conflict semantics."""

        if len(self.best_common_ancestors) != 1:
            raise ConflictError(
                [
                    "branches have multiple best common ancestors: "
                    + ", ".join(self.best_common_ancestors)
                ]
            )
        return self.best_common_ancestors[0]

    def evidence(self) -> dict[str, Any]:
        """Return deterministic bounded evidence suitable for identity binding."""

        return {
            "format": REVISION_DAG_ANALYSIS_FORMAT,
            "left_revision_id": self.left_revision_id,
            "right_revision_id": self.right_revision_id,
            "best_common_ancestors": list(self.best_common_ancestors),
            "common_ancestor_count": self.common_ancestor_count,
            "nodes_visited": self.nodes_visited,
            "edges_visited": self.edges_visited,
            "limits": {
                "nodes": self.max_nodes,
                "edges": self.max_edges,
            },
        }


def analyze_common_ancestors(
    source: ParentSource,
    left: str,
    right: str,
    *,
    max_nodes: int = MAX_REVISION_DAG_NODES,
    max_edges: int = MAX_REVISION_DAG_EDGES,
) -> RevisionDagAnalysis:
    """Analyze the union ancestry graph once and return deterministic merge bases."""

    _validate_internal_limit(
        max_nodes,
        maximum=MAX_REVISION_DAG_NODES,
        name="max_nodes",
    )
    _validate_internal_limit(
        max_edges,
        maximum=MAX_REVISION_DAG_EDGES,
        name="max_edges",
    )
    parents: dict[str, tuple[str, ...]] = {}
    reachability: dict[str, int] = {}
    edges_visited = 0
    queue: deque[tuple[str, int]] = deque(((left, _LEFT), (right, _RIGHT)))

    while queue:
        revision, side = queue.popleft()
        previous = reachability.get(revision, 0)
        if previous & side:
            continue

        if revision not in parents:
            if len(parents) >= max_nodes:
                raise ValidationError(
                    "REVISION_DAG_NODE_LIMIT_EXCEEDED",
                    f"revision ancestry exceeds the node limit {max_nodes}",
                )
            raw_parents = tuple(
                str(parent) for parent in _load_parents(source, revision) if parent is not None
            )
            edges_visited += len(raw_parents)
            if edges_visited > max_edges:
                raise ValidationError(
                    "REVISION_DAG_EDGE_LIMIT_EXCEEDED",
                    f"revision ancestry exceeds the edge limit {max_edges}",
                )
            parents[revision] = tuple(dict.fromkeys(raw_parents))

        reachability[revision] = previous | side
        for parent in parents[revision]:
            queue.append((parent, side))

    common = {revision for revision, sides in reachability.items() if sides == _BOTH}
    best = _best_common_ancestors(parents, common)
    if not common:
        raise ConflictError(["branches have no common ancestor"])
    return RevisionDagAnalysis(
        left_revision_id=left,
        right_revision_id=right,
        best_common_ancestors=best,
        common_ancestor_count=len(common),
        nodes_visited=len(parents),
        edges_visited=edges_visited,
        max_nodes=max_nodes,
        max_edges=max_edges,
    )


def ancestor_distances(
    source: ParentSource,
    revision: str,
    *,
    max_nodes: int = MAX_REVISION_DAG_NODES,
    max_edges: int = MAX_REVISION_DAG_EDGES,
) -> dict[str, int]:
    """Return bounded shortest ancestor distances for compatibility and diagnostics."""

    _validate_internal_limit(
        max_nodes,
        maximum=MAX_REVISION_DAG_NODES,
        name="max_nodes",
    )
    _validate_internal_limit(
        max_edges,
        maximum=MAX_REVISION_DAG_EDGES,
        name="max_edges",
    )
    distances = {revision: 0}
    parents: dict[str, tuple[str, ...]] = {}
    edges_visited = 0
    queue: deque[str] = deque([revision])
    while queue:
        current = queue.popleft()
        if current not in parents:
            if len(parents) >= max_nodes:
                raise ValidationError(
                    "REVISION_DAG_NODE_LIMIT_EXCEEDED",
                    f"revision ancestry exceeds the node limit {max_nodes}",
                )
            raw_parents = tuple(
                str(parent) for parent in _load_parents(source, current) if parent is not None
            )
            edges_visited += len(raw_parents)
            if edges_visited > max_edges:
                raise ValidationError(
                    "REVISION_DAG_EDGE_LIMIT_EXCEEDED",
                    f"revision ancestry exceeds the edge limit {max_edges}",
                )
            parents[current] = tuple(dict.fromkeys(raw_parents))
        for parent in parents[current]:
            if parent not in distances:
                distances[parent] = distances[current] + 1
                queue.append(parent)
    return distances


def _load_parents(
    source: ParentSource,
    revision: str,
) -> tuple[str | None, str | None]:
    # sqlite3.Connection is callable, so prefer an explicit connection check
    # before treating the source as a parent-loader callback.
    if isinstance(source, sqlite3.Connection):
        row = source.execute(
            "SELECT parent1_id, parent2_id FROM revisions WHERE id = ?",
            (revision,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"revision {revision!r} not found")
        return row[0], row[1]
    return source(revision)


def _best_common_ancestors(
    parents: dict[str, tuple[str, ...]],
    common: set[str],
) -> tuple[str, ...]:
    """Find maximal common descendants in one deterministic topological pass."""

    child_counts = {revision: 0 for revision in parents}
    for child_parents in parents.values():
        for parent in child_parents:
            if parent not in child_counts:
                raise NotFoundError(f"revision {parent!r} not found")
            child_counts[parent] += 1

    ready = [revision for revision, count in child_counts.items() if count == 0]
    heapq.heapify(ready)
    common_descendant = {revision: False for revision in parents}
    non_best: set[str] = set()
    processed = 0
    while ready:
        revision = heapq.heappop(ready)
        processed += 1
        propagates_common = revision in common or common_descendant[revision]
        for parent in parents[revision]:
            if propagates_common:
                common_descendant[parent] = True
                if parent in common:
                    non_best.add(parent)
            child_counts[parent] -= 1
            if child_counts[parent] == 0:
                heapq.heappush(ready, parent)

    if processed != len(parents):
        raise ValidationError(
            "REVISION_DAG_CYCLE",
            "revision ancestry contains a cycle",
        )
    return tuple(sorted(common - non_best))


def _validate_internal_limit(value: Any, *, maximum: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")


__all__ = [
    "REVISION_DAG_ANALYSIS_FORMAT",
    "RevisionDagAnalysis",
    "analyze_common_ancestors",
    "ancestor_distances",
]
