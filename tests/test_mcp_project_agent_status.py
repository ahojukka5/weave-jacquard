from __future__ import annotations

from typing import Any

from weave_frontend import mcp_project_agent_status
from weave_frontend.project_agent_status import ProjectAgentStatusService


class _Statuses:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def page(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((args, kwargs))
        return {
            "format": "weave-project-agent-status-v1",
            "catalog_id": "catalog-1",
            "page_id": "page-1",
        }


def test_project_agent_status_page_forwards_catalog_cursor_and_bounds(monkeypatch) -> None:
    statuses = _Statuses()
    monkeypatch.setattr(
        mcp_project_agent_status,
        "project_agent_statuses",
        lambda: statuses,
    )

    response = mcp_project_agent_status.project_agent_status_page(
        "demo",
        start_after_branch="feature-a",
        catalog_id="catalog-1",
        limit=7,
        checkpoint_scan_limit=41,
    )

    assert response["ok"] is True
    assert response["result"]["page_id"] == "page-1"
    assert statuses.calls == [
        (
            ("demo",),
            {
                "start_after_branch": "feature-a",
                "catalog_id": "catalog-1",
                "limit": 7,
                "checkpoint_scan_limit": 41,
            },
        )
    ]


def test_project_agent_status_factory_uses_shared_checkpoint_registry() -> None:
    mcp_project_agent_status.project_agent_statuses.cache_clear()

    service = mcp_project_agent_status.project_agent_statuses()

    assert isinstance(service, ProjectAgentStatusService)
    assert service.checkpoints is mcp_project_agent_status.agent_checkpoints()
    assert service.workspace is service.checkpoints.workspace
    mcp_project_agent_status.project_agent_statuses.cache_clear()
