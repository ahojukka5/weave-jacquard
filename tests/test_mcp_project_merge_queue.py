from __future__ import annotations

from typing import Any

from weave_frontend import mcp_agent_checkpoint, mcp_project_merge_queue
from weave_frontend.merges import ProjectMergeQueueService


class _Queues:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def page(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((args, kwargs))
        return {
            "format": "weave-project-merge-queue-v1",
            "catalog_id": "catalog-1",
            "page_id": "page-1",
        }


def test_project_merge_queue_page_forwards_target_catalog_cursor_and_bounds(
    monkeypatch,
) -> None:
    queues = _Queues()
    monkeypatch.setattr(
        mcp_project_merge_queue,
        "project_merge_queues",
        lambda: queues,
    )

    response = mcp_project_merge_queue.project_merge_queue_page(
        "demo",
        target_branch="release",
        start_after_source="feature-a",
        catalog_id="catalog-1",
        limit=7,
        checkpoint_scan_limit=41,
        conflict_limit=11,
        changed_document_limit=13,
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
            },
        )
    ]


def test_project_merge_queue_factory_uses_shared_preview_and_status_services() -> None:
    caches = (
        mcp_project_merge_queue.project_merge_queues,
        mcp_project_merge_queue.merge_previews,
        mcp_project_merge_queue.project_agent_statuses,
        mcp_agent_checkpoint.agent_checkpoints,
    )
    for cached in caches:
        cached.cache_clear()

    service = mcp_project_merge_queue.project_merge_queues()

    assert isinstance(service, ProjectMergeQueueService)
    assert service.previews is mcp_project_merge_queue.merge_previews()
    assert service.statuses is mcp_project_merge_queue.project_agent_statuses()
    assert service.workspace is service.previews.workspace
    assert service.workspace is service.statuses.workspace

    for cached in caches:
        cached.cache_clear()
