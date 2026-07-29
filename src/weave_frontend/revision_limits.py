"""Central resource ceilings for revision-wide and history-wide operations."""

from __future__ import annotations

from typing import Any

from .errors import ValidationError
from .snapshot_codec import (
    MAX_QUALIFIED_NAME_BYTES,
    MAX_REVISION_DECODED_BYTES,
    MAX_REVISION_MODULES,
    MAX_SNAPSHOT_COMPRESSED_BYTES,
    MAX_SNAPSHOT_DECOMPRESSED_BYTES,
)

MAX_BUILD_DOCUMENTS = 256
MAX_REVISION_DAG_NODES = 65_536
MAX_REVISION_DAG_EDGES = 131_072
MAX_BRANCH_HISTORY_PAGE_SIZE = 200

REVISION_RESOURCE_LIMITS: dict[str, int] = {
    "branch_history_page_size": MAX_BRANCH_HISTORY_PAGE_SIZE,
    "build_documents": MAX_BUILD_DOCUMENTS,
    "qualified_name_bytes": MAX_QUALIFIED_NAME_BYTES,
    "revision_dag_edges": MAX_REVISION_DAG_EDGES,
    "revision_dag_nodes": MAX_REVISION_DAG_NODES,
    "revision_decoded_bytes": MAX_REVISION_DECODED_BYTES,
    "revision_modules": MAX_REVISION_MODULES,
    "snapshot_compressed_bytes": MAX_SNAPSHOT_COMPRESSED_BYTES,
    "snapshot_decompressed_bytes": MAX_SNAPSHOT_DECOMPRESSED_BYTES,
}


def require_bounded_int(
    value: Any,
    *,
    code: str,
    name: str,
    minimum: int,
    maximum: int,
) -> int:
    """Return one integer in an explicit closed interval or fail predictably."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(code, f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise ValidationError(
            code,
            f"{name} must be between {minimum} and {maximum}",
        )
    return value


def require_nonnegative_int(value: Any, *, code: str, name: str) -> int:
    """Return one non-negative integer while rejecting booleans explicitly."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValidationError(code, f"{name} must be a non-negative integer")
    return value


__all__ = [
    "MAX_BRANCH_HISTORY_PAGE_SIZE",
    "MAX_BUILD_DOCUMENTS",
    "MAX_QUALIFIED_NAME_BYTES",
    "MAX_REVISION_DAG_EDGES",
    "MAX_REVISION_DAG_NODES",
    "MAX_REVISION_DECODED_BYTES",
    "MAX_REVISION_MODULES",
    "MAX_SNAPSHOT_COMPRESSED_BYTES",
    "MAX_SNAPSHOT_DECOMPRESSED_BYTES",
    "REVISION_RESOURCE_LIMITS",
    "require_bounded_int",
    "require_nonnegative_int",
]
