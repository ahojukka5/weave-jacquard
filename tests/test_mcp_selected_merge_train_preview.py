from __future__ import annotations

from typing import Any

from weave_frontend import (
    mcp_agent_checkpoint,
    mcp_build,
    mcp_project_agent_status,
    mcp_project_merge_queue,
    mcp_selected_merge_train_preview,
)
from weave_frontend.merges import SelectedMergeTrainPreviewService


class _Trains:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def preview(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((args, kwargs))
        return {
            "format": "weave-selected-merge-train-preview-v1",
            "train_id": "train-1",
        }


def test_selected_merge_train_forwards_order_catalog_and_bounds(monkeypatch) -> None:
    trains = _Trains()
    monkeypatch.setattr(
        mcp_selected_merge_train_preview,
        "selected_merge_train_previews",
        lambda: trains,
    )

    response = mcp_selected_merge_train_preview.selected_merge_train_preview(
        "demo",
        "release",
        ["feature-b", "feature-a"],
        "catalog-1",
        conflict_limit=7,
        changed_document_limit=11,
    )

    assert response["ok"] is True
    assert response["result"]["train_id"] == "train-1"
    assert trains.calls == [
        (
            (
                "demo",
                "release",
                ["feature-b", "feature-a"],
                "catalog-1",
            ),
            {
                "conflict_limit": 7,
                "changed_document_limit": 11,
            },
        )
    ]


def test_selected_merge_train_factory_uses_shared_queue_service() -> None:
    caches = (
        mcp_selected_merge_train_preview.selected_merge_train_previews,
        mcp_project_merge_queue.project_merge_queues,
        mcp_project_agent_status.project_agent_statuses,
        mcp_agent_checkpoint.agent_checkpoints,
        mcp_build.merge_previews,
    )
    for cached in caches:
        cached.cache_clear()

    service = mcp_selected_merge_train_preview.selected_merge_train_previews()

    assert isinstance(service, SelectedMergeTrainPreviewService)
    assert service.queues is mcp_project_merge_queue.project_merge_queues()
    assert service.previews is service.queues.previews
    assert service.workspace is service.queues.workspace

    for cached in caches:
        cached.cache_clear()
