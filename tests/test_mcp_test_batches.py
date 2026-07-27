from __future__ import annotations

from typing import Any

from weave_frontend import mcp_test_batches


class _Batches:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def run(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("run", args, kwargs))
        return {"batch_id": "a" * 32, "status": "passed"}

    def get(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("get", args, kwargs))
        return {"batch_id": args[0], "status": "passed"}


def test_batch_run_forwards_explicit_order_and_exact_revision(monkeypatch) -> None:
    batches = _Batches()
    monkeypatch.setattr(mcp_test_batches, "test_batches", lambda: batches)

    response = mcp_test_batches.test_batch_run(
        "demo",
        ["beta", "alpha"],
        branch="feature",
        revision_id="revision-exact",
    )

    assert response == {
        "ok": True,
        "result": {"batch_id": "a" * 32, "status": "passed"},
    }
    assert batches.calls == [
        (
            "run",
            ("demo", ["beta", "alpha"]),
            {"branch": "feature", "revision_id": "revision-exact"},
        )
    ]


def test_batch_get_forwards_immutable_identity(monkeypatch) -> None:
    batches = _Batches()
    monkeypatch.setattr(mcp_test_batches, "test_batches", lambda: batches)

    response = mcp_test_batches.test_batch_get("a" * 32)

    assert response["result"]["batch_id"] == "a" * 32
    assert batches.calls == [("get", ("a" * 32,), {})]
