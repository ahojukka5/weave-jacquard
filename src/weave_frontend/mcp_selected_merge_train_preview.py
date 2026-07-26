"""Production MCP registration for explicit order-aware merge-train previews."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from .mcp_project_merge_queue import project_merge_queues
from .mcp_server import _result, mcp
from .selected_merge_train_preview import SelectedMergeTrainPreviewService


@lru_cache(maxsize=1)
def selected_merge_train_previews() -> SelectedMergeTrainPreviewService:
    """Return the shared in-memory selected merge-train preview service."""

    return SelectedMergeTrainPreviewService(project_merge_queues())


@mcp.tool()
def selected_merge_train_preview(
    project: str,
    target_branch: str,
    sources: list[str],
    catalog_id: str,
    conflict_limit: int = 20,
    changed_document_limit: int = 50,
) -> dict[str, Any]:
    """Simulate ordered exact-catalog source merges without compiler or publication."""

    return _result(
        lambda: selected_merge_train_previews().preview(
            project,
            target_branch,
            sources,
            catalog_id,
            conflict_limit=conflict_limit,
            changed_document_limit=changed_document_limit,
        )
    )
