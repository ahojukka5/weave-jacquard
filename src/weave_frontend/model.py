"""Typed data returned by the Weave workspace service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

JsonObject = dict[str, Any]


@dataclass(frozen=True, slots=True)
class MutationResult:
    revision_id: str
    branch: str
    created_node_ids: tuple[str, ...]
    diagnostics: tuple[JsonObject, ...] = ()


@dataclass(frozen=True, slots=True)
class MergeResult:
    revision_id: str
    target_branch: str
    source_branch: str
    changed_symbols: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SymbolSummary:
    qualified_name: str
    kind: str
    signature: str
    module: str
    node_id: str
