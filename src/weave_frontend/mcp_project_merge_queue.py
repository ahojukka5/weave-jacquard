"""Production MCP registration for stable project merge queues."""

from __future__ import annotations

from typing import Any

from .mcp_build import merge_previews
from .mcp_project_agent_status import project_agent_statuses
from .mcp_server import _result, mcp
from .merges import ProjectMergeQueueService
from .runtime import runtime_service


@runtime_service(
    "project_merge_queues",
    depends_on=("merge_previews", "project_agent_statuses"),
)
def project_merge_queues() -> ProjectMergeQueueService:
    """Return the shared stable project merge-queue service."""

    return ProjectMergeQueueService(
        merge_previews(),
        project_agent_statuses(),
    )


@mcp.tool()
def project_merge_queue_page(
    project: str,
    target_branch: str = "main",
    start_after_source: str | None = None,
    catalog_id: str | None = None,
    limit: int = 10,
    checkpoint_scan_limit: int = 100,
    conflict_limit: int = 20,
    changed_document_limit: int = 50,
) -> dict[str, Any]:
    """Page compact exact-head merge previews for project source branches."""

    return _result(
        lambda: project_merge_queues().page(
            project,
            target_branch,
            start_after_source=start_after_source,
            catalog_id=catalog_id,
            limit=limit,
            checkpoint_scan_limit=checkpoint_scan_limit,
            conflict_limit=conflict_limit,
            changed_document_limit=changed_document_limit,
        )
    )
