"""Production MCP registration for checkpoint timelines and comparisons."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from .agent_checkpoint_timeline import AgentCheckpointTimelineService
from .mcp_agent_checkpoint import agent_checkpoints
from .mcp_server import _result, mcp


@lru_cache(maxsize=1)
def checkpoint_timelines() -> AgentCheckpointTimelineService:
    """Return the shared bounded checkpoint timeline service."""

    return AgentCheckpointTimelineService(agent_checkpoints())


@mcp.tool()
def branch_checkpoint_history_page(
    project: str,
    branch: str = "main",
    start_revision_id: str | None = None,
    limit: int = 20,
    revision_scan_limit: int = 200,
) -> dict[str, Any]:
    """Read bounded newest-to-oldest first-parent checkpoint history."""

    return _result(
        lambda: checkpoint_timelines().page(
            project,
            branch,
            start_revision_id=start_revision_id,
            limit=limit,
            revision_scan_limit=revision_scan_limit,
        )
    )


@mcp.tool()
def branch_checkpoint_compare(
    project: str,
    base_checkpoint_revision_id: str,
    target_checkpoint_revision_id: str,
) -> dict[str, Any]:
    """Compare two exact checkpoint revisions without semantic inference."""

    return _result(
        lambda: checkpoint_timelines().compare(
            project,
            base_checkpoint_revision_id,
            target_checkpoint_revision_id,
        )
    )
