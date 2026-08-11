from __future__ import annotations

from typing import Any

from weave_frontend import (
    mcp_agent_checkpoint,
    mcp_build,
    mcp_preflight,
    mcp_project_agent_status,
    mcp_project_merge_impact_queue,
    mcp_project_merge_queue,
)
from weave_frontend.merges import ProjectMergeImpactQueueService


class _Queues:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def page(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((args, kwargs))
        return {
            "format": "weave-project-merge-impact-queue-v1",
            "catalog_id": "catalog-1",
            "page_id": "page-1",
        }


def test_project_merge_impact_queue_forwards_catalog_and_all_bounds(monkeypatch) -> None:
    queues = _Queues()
    monkeypatch.setattr(
        mcp_project_merge_impact_queue,
        "project_merge_impact_queues",
        lambda: queues,
    )

    response = mcp_project_merge_impact_queue.project_merge_impact_queue_page(
        "demo",
        target_branch="release",
        start_after_source="feature-a",
        catalog_id="catalog-1",
        limit=7,
        checkpoint_scan_limit=41,
        conflict_limit=11,
        changed_document_limit=13,
        affected_target_limit=17,
        coverage_document_limit=19,
    )

    assert response["ok"] is True
    assert response["result"]["page_id"] == "page-1"
    assert queues.calls == [
        (
            ("demo", "release"),
            {
                "start_after_source": "feature-a",
                "catalog_id": "catalog-1",
                "limit": 7,
                "checkpoint_scan_limit": 41,
                "conflict_limit": 11,
                "changed_document_limit": 13,
                "affected_target_limit": 17,
                "coverage_document_limit": 19,
            },
        )
    ]


def test_project_merge_impact_queue_factory_uses_shared_services() -> None:
    caches = (
        mcp_project_merge_impact_queue.project_merge_impact_queues,
        mcp_project_merge_queue.project_merge_queues,
        mcp_project_agent_status.project_agent_statuses,
        mcp_agent_checkpoint.agent_checkpoints,
        mcp_build.merge_previews,
        mcp_build.merge_impacts,
        mcp_build.build_targets,
        mcp_preflight.merge_policies,
    )
    for cached in caches:
        cached.cache_clear()

    service = mcp_project_merge_impact_queue.project_merge_impact_queues()

    assert isinstance(service, ProjectMergeImpactQueueService)
    assert service.queues is mcp_project_merge_queue.project_merge_queues()
    assert service.impacts is mcp_build.merge_impacts()
    assert service.policies is mcp_preflight.merge_policies()
    assert service.workspace is service.queues.workspace
    assert service.workspace is service.impacts.previews.workspace
    assert service.workspace is service.policies.workspace

    for cached in caches:
        cached.cache_clear()
