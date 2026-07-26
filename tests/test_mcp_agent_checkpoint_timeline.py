from __future__ import annotations

from typing import Any

from weave_frontend import mcp_agent_checkpoint_timeline
from weave_frontend.agent_checkpoint_timeline import AgentCheckpointTimelineService


class _Timelines:
    def __init__(self) -> None:
        self.page_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.compare_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def page(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.page_calls.append((args, kwargs))
        return {
            "format": "weave-agent-checkpoint-timeline-v1",
            "page_id": "page-1",
        }

    def compare(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.compare_calls.append((args, kwargs))
        return {
            "format": "weave-agent-checkpoint-comparison-v1",
            "comparison_id": "comparison-1",
        }


def test_checkpoint_history_page_forwards_exact_bounds(monkeypatch) -> None:
    timelines = _Timelines()
    monkeypatch.setattr(
        mcp_agent_checkpoint_timeline,
        "checkpoint_timelines",
        lambda: timelines,
    )

    response = mcp_agent_checkpoint_timeline.branch_checkpoint_history_page(
        "demo",
        branch="feature",
        start_revision_id="revision-old",
        limit=7,
        revision_scan_limit=41,
    )

    assert response["ok"] is True
    assert response["result"]["page_id"] == "page-1"
    assert timelines.page_calls == [
        (
            ("demo", "feature"),
            {
                "start_revision_id": "revision-old",
                "limit": 7,
                "revision_scan_limit": 41,
            },
        )
    ]


def test_checkpoint_compare_forwards_exact_revisions(monkeypatch) -> None:
    timelines = _Timelines()
    monkeypatch.setattr(
        mcp_agent_checkpoint_timeline,
        "checkpoint_timelines",
        lambda: timelines,
    )

    response = mcp_agent_checkpoint_timeline.branch_checkpoint_compare(
        "demo",
        "checkpoint-a",
        "checkpoint-b",
    )

    assert response["ok"] is True
    assert response["result"]["comparison_id"] == "comparison-1"
    assert timelines.compare_calls == [
        (("demo", "checkpoint-a", "checkpoint-b"), {})
    ]


def test_checkpoint_timeline_factory_uses_shared_registry() -> None:
    mcp_agent_checkpoint_timeline.checkpoint_timelines.cache_clear()

    service = mcp_agent_checkpoint_timeline.checkpoint_timelines()

    assert isinstance(service, AgentCheckpointTimelineService)
    assert service.registry is mcp_agent_checkpoint_timeline.agent_checkpoints()
    assert service.workspace is service.registry.workspace
    mcp_agent_checkpoint_timeline.checkpoint_timelines.cache_clear()
