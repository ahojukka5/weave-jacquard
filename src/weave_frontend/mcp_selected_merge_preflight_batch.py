"""Production MCP registration for explicit selected-source preflight batches."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from .mcp_preflight import merge_preflights
from .mcp_project_merge_queue import project_merge_queues
from .mcp_server import _result, mcp
from .selected_merge_preflight_batch import SelectedMergePreflightBatchService


@lru_cache(maxsize=1)
def selected_merge_preflight_batches() -> SelectedMergePreflightBatchService:
    """Return the shared explicit compiler-backed preflight batch service."""

    return SelectedMergePreflightBatchService(
        project_merge_queues(),
        merge_preflights(),
    )


@mcp.tool()
def selected_merge_preflight_batch(
    project: str,
    target_branch: str,
    sources: list[str],
    catalog_id: str,
    allow_uncovered_sources: list[str] | None = None,
    validation_result_limit: int = 20,
    document_limit: int = 100,
) -> dict[str, Any]:
    """Run compiler-backed preflight for explicit exact-catalog source branches."""

    return _result(
        lambda: selected_merge_preflight_batches().run(
            project,
            target_branch,
            sources,
            catalog_id,
            allow_uncovered_sources=allow_uncovered_sources,
            validation_result_limit=validation_result_limit,
            document_limit=document_limit,
        )
    )
