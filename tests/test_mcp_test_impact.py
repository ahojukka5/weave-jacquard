from __future__ import annotations

from typing import Any

from weave_frontend import mcp_test_impact


class _Plans:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def page(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((args, kwargs))
        return {"plan_id": "a" * 64, "total_impacted_test_count": 2}


def test_test_impact_plan_forwards_exact_revisions_and_bounds(monkeypatch) -> None:
    plans = _Plans()
    monkeypatch.setattr(mcp_test_impact, "test_impact_plans", lambda: plans)

    response = mcp_test_impact.test_impact_plan(
        "demo",
        "revision-base",
        branch="feature",
        target_revision_id="revision-target",
        start_after_name="alpha",
        limit=20,
        evidence_limit=30,
    )

    assert response == {
        "ok": True,
        "result": {"plan_id": "a" * 64, "total_impacted_test_count": 2},
    }
    assert plans.calls == [
        (
            ("demo", "revision-base"),
            {
                "branch": "feature",
                "target_revision_id": "revision-target",
                "start_after_name": "alpha",
                "limit": 20,
                "evidence_limit": 30,
            },
        )
    ]
