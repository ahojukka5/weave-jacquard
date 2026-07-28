"""Central resource ceilings for structural source and tree operations."""

from __future__ import annotations

MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_TREE_DEPTH = 512
MAX_TREE_NODES = 100_000
MAX_ATOM_VALUE_BYTES = 1024 * 1024
MAX_TREE_VALUE_BYTES = 8 * 1024 * 1024
MAX_RENDERED_SOURCE_BYTES = 16 * 1024 * 1024


__all__ = [
    "MAX_ATOM_VALUE_BYTES",
    "MAX_RENDERED_SOURCE_BYTES",
    "MAX_SOURCE_BYTES",
    "MAX_TREE_DEPTH",
    "MAX_TREE_NODES",
    "MAX_TREE_VALUE_BYTES",
]
