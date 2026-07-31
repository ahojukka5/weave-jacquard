"""Production MCP registration for stable project merge-impact queues."""

from __future__ import annotations

from typing import Any

from .mcp_build import merge_impacts
from .mcp_preflight import merge_policies
from .mcp_project_merge_queue import project_merge_queues
from .mcp_server import _result, mcp
from .project_merge_impact_queue import ProjectMergeImpactQueueService
from .runtime_container import runtime_service


@runtime_service(
    "project_merge_impact_queues",
    depends_on=("project_merge_queues", "merge_impacts", "merge_policies"),
)
def project_merge_impact_queues() -> ProjectMergeImpactQueueService:
    """Return the shared non-compiling project merge-impact queue service."""

    return ProjectMergeImpactQueueService(
        project_merge_queues(),
        merge_impacts(),
        merge_policies(),
    )


@mcp.tool()
def project_merge_impact_queue_page(
    project: str,
    target_branch: str = "main",
    start_after_source: str | None = None,
    catalog_id: str | None = None,
    limit: int = 5,
    checkpoint_scan_limit: int = 100,
    conflict_limit: int = 20,
    changed_document_limit: int = 50,
    affected_target_limit: int = 50,
    coverage_document_limit: int = 100,
) -> dict[str, Any]:
    """Page exact-head merge, policy, and target-coverage evidence without builds."""

    return _result(
        lambda: project_merge_impact_queues().page(
            project,
            target_branch,
            start_after_source=start_after_source,
            catalog_id=catalog_id,
            limit=limit,
            checkpoint_scan_limit=checkpoint_scan_limit,
            conflict_limit=conflict_limit,
            changed_document_limit=changed_document_limit,
            affected_target_limit=affected_target_limit,
            coverage_document_limit=coverage_document_limit,
        )
    )
