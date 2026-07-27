from __future__ import annotations

from typing import Any

from weave_frontend import mcp_merge_test_impact


class _Plans:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def page(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((args, kwargs))
        return {"plan_id": "a" * 64, "preview_id": "preview-exact"}


def test_merge_test_impact_forwards_preview_and_bounds(monkeypatch) -> None:
    plans = _Plans()
    monkeypatch.setattr(
        mcp_merge_test_impact,
        "merge_test_impact_plans",
        lambda: plans,
    )

    response = mcp_merge_test_impact.branch_merge_test_impact(
        "demo",
        "main",
        "feature",
        preview_id="preview-exact",
        start_after_name="alpha",
        limit=20,
        evidence_limit=30,
    )

    assert response == {
        "ok": True,
        "result": {"plan_id": "a" * 64, "preview_id": "preview-exact"},
    }
    assert plans.calls == [
        (
            ("demo", "main", "feature"),
            {
                "preview_id": "preview-exact",
                "start_after_name": "alpha",
                "limit": 20,
                "evidence_limit": 30,
            },
        )
    ]
