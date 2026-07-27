from __future__ import annotations

from typing import Any

from weave_frontend import mcp_test_runs


class _Runs:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def capabilities(self) -> dict[str, Any]:
        self.calls.append(("capabilities", (), {}))
        return {"available": True, "backend": "bubblewrap"}

    def run(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("run", args, kwargs))
        return {"run_id": "a" * 32, "passed": True}

    def get(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("get", args, kwargs))
        return {"run_id": args[0], "passed": True}

    def output_page(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("output_page", args, kwargs))
        return {"run_id": args[0], "stream": args[1], "returned_bytes": 3}


def test_sandbox_capabilities_forwards_probe(monkeypatch) -> None:
    runs = _Runs()
    monkeypatch.setattr(mcp_test_runs, "test_runs", lambda: runs)

    response = mcp_test_runs.sandbox_capabilities()

    assert response == {
        "ok": True,
        "result": {"available": True, "backend": "bubblewrap"},
    }
    assert runs.calls == [("capabilities", (), {})]


def test_test_run_forwards_exact_revision(monkeypatch) -> None:
    runs = _Runs()
    monkeypatch.setattr(mcp_test_runs, "test_runs", lambda: runs)

    response = mcp_test_runs.test_run(
        "demo",
        "smoke",
        branch="feature",
        revision_id="revision-exact",
    )

    assert response["ok"] is True
    assert response["result"]["run_id"] == "a" * 32
    assert runs.calls == [
        (
            "run",
            ("demo", "smoke"),
            {"branch": "feature", "revision_id": "revision-exact"},
        )
    ]


def test_run_reads_forward_identity_and_output_bounds(monkeypatch) -> None:
    runs = _Runs()
    monkeypatch.setattr(mcp_test_runs, "test_runs", lambda: runs)

    get_response = mcp_test_runs.test_run_get("a" * 32)
    page_response = mcp_test_runs.test_run_output_page(
        "a" * 32,
        "stderr",
        start_byte=4,
        max_bytes=8,
    )

    assert get_response["result"]["passed"] is True
    assert page_response["result"]["returned_bytes"] == 3
    assert runs.calls == [
        ("get", ("a" * 32,), {}),
        (
            "output_page",
            ("a" * 32, "stderr"),
            {"start_byte": 4, "max_bytes": 8},
        ),
    ]
