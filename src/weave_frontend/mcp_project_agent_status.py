"""Production MCP registration for project-wide agent supervision pages."""

from __future__ import annotations

from typing import Any

from .mcp_agent_checkpoint import agent_checkpoints
from .mcp_server import _result, mcp
from .project_agent_status import ProjectAgentStatusService
from .runtime_container import runtime_service


@runtime_service("project_agent_statuses", depends_on=("agent_checkpoints",))
def project_agent_statuses() -> ProjectAgentStatusService:
    """Return the shared bounded project agent-status service."""

    return ProjectAgentStatusService(agent_checkpoints())


@mcp.tool()
def project_agent_status_page(
    project: str,
    start_after_branch: str | None = None,
    catalog_id: str | None = None,
    limit: int = 25,
    checkpoint_scan_limit: int = 100,
) -> dict[str, Any]:
    """Page exact branch heads and their latest bounded checkpoint evidence."""

    return _result(
        lambda: project_agent_statuses().page(
            project,
            start_after_branch=start_after_branch,
            catalog_id=catalog_id,
            limit=limit,
            checkpoint_scan_limit=checkpoint_scan_limit,
        )
    )
