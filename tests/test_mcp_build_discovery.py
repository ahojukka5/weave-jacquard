from __future__ import annotations

from typing import Any

from weave_frontend import mcp_build_discovery
from weave_frontend.errors import ValidationError


class _Discovery:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def page(self, project: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((project, kwargs))
        return {
            "format": "weave-build-list-page-v1",
            "catalog_id": "a" * 64,
            "project": project,
            "builds": [],
        }


def test_mcp_build_list_forwards_filters_and_cursor(monkeypatch) -> None:
    discovery = _Discovery()
    monkeypatch.setattr(mcp_build_discovery, "build_discovery", lambda: discovery)

    response = mcp_build_discovery.build_list_page(
        "demo",
        branch="feature",
        revision_id="revision-1",
        status="failed",
        document="support.weave",
        target="wasm32-wasi",
        start_after_build_id="1" * 32,
        catalog_id="2" * 64,
        limit=7,
    )

    assert response["ok"] is True
    assert response["result"]["format"] == "weave-build-list-page-v1"
    assert discovery.calls == [
        (
            "demo",
            {
                "branch": "feature",
                "revision_id": "revision-1",
                "status": "failed",
                "document": "support.weave",
                "target": "wasm32-wasi",
                "start_after_build_id": "1" * 32,
                "catalog_id": "2" * 64,
                "limit": 7,
            },
        )
    ]


def test_mcp_build_list_returns_structured_request_errors(monkeypatch) -> None:
    class _Rejected:
        def page(self, project: str, **kwargs: Any) -> dict[str, Any]:
            raise ValidationError("STALE_BUILD_CATALOG", "catalog changed")

    monkeypatch.setattr(mcp_build_discovery, "build_discovery", lambda: _Rejected())

    response = mcp_build_discovery.build_list_page(
        "demo",
        catalog_id="1" * 64,
    )

    assert response["ok"] is False
    assert response["error"]["code"] == "STALE_BUILD_CATALOG"
    assert response["error"]["message"] == "catalog changed"
