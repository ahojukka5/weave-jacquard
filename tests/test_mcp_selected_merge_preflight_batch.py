from __future__ import annotations

from typing import Any

from weave_frontend import (
    mcp_agent_checkpoint,
    mcp_build,
    mcp_preflight,
    mcp_project_agent_status,
    mcp_project_merge_queue,
    mcp_selected_merge_preflight_batch,
)
from weave_frontend.selected_merge_preflight_batch import (
    SelectedMergePreflightBatchService,
)


class _Batches:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def run(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((args, kwargs))
        return {
            "format": "weave-selected-merge-preflight-batch-v1",
            "batch_id": "batch-1",
        }


def test_selected_preflight_batch_forwards_explicit_selection_and_bounds(
    monkeypatch,
) -> None:
    batches = _Batches()
    monkeypatch.setattr(
        mcp_selected_merge_preflight_batch,
        "selected_merge_preflight_batches",
        lambda: batches,
    )

    response = mcp_selected_merge_preflight_batch.selected_merge_preflight_batch(
        "demo",
        "release",
        ["feature-b", "feature-a"],
        "catalog-1",
        allow_uncovered_sources=["feature-b"],
        validation_result_limit=7,
        document_limit=11,
    )

    assert response["ok"] is True
    assert response["result"]["batch_id"] == "batch-1"
    assert batches.calls == [
        (
            (
                "demo",
                "release",
                ["feature-b", "feature-a"],
                "catalog-1",
            ),
            {
                "allow_uncovered_sources": ["feature-b"],
                "validation_result_limit": 7,
                "document_limit": 11,
            },
        )
    ]


def test_selected_preflight_batch_factory_uses_shared_queue_and_preflight() -> None:
    caches = (
        mcp_selected_merge_preflight_batch.selected_merge_preflight_batches,
        mcp_project_merge_queue.project_merge_queues,
        mcp_project_agent_status.project_agent_statuses,
        mcp_agent_checkpoint.agent_checkpoints,
        mcp_build.merge_previews,
        mcp_build.merge_impacts,
        mcp_build.merge_validation_sets,
        mcp_build.merge_validations,
        mcp_build.build_targets,
        mcp_preflight.merge_policies,
        mcp_preflight.merge_preflights,
    )
    for cached in caches:
        cached.cache_clear()

    service = mcp_selected_merge_preflight_batch.selected_merge_preflight_batches()

    assert isinstance(service, SelectedMergePreflightBatchService)
    assert service.queues is mcp_project_merge_queue.project_merge_queues()
    assert service.preflights is mcp_preflight.merge_preflights()
    assert service.workspace is service.queues.workspace
    assert service.workspace is service.preflights.impacts.previews.workspace

    for cached in caches:
        cached.cache_clear()
