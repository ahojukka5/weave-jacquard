from __future__ import annotations

from typing import Any

from weave_frontend import mcp_build, mcp_test_targets
from weave_frontend.metadata_build_targets import BuildTargetRegistry
from weave_frontend.metadata_merge_impact import MergeTargetImpactService


class _Tests:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def set(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("set", args, kwargs))
        return {"name": args[2], "base_revision_id": kwargs["expected_revision_id"]}

    def get(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("get", args, kwargs))
        return {"name": args[1], "revision_id": kwargs["revision_id"]}

    def list(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("list", args, kwargs))
        return [{"name": "smoke"}]

    def delete(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("delete", args, kwargs))
        return {"name": args[2], "base_revision_id": kwargs["expected_revision_id"]}


def test_test_target_set_forwards_complete_definition(monkeypatch) -> None:
    tests = _Tests()
    monkeypatch.setattr(mcp_test_targets, "test_targets", lambda: tests)

    response = mcp_test_targets.test_target_set(
        project="demo",
        branch="feature",
        name="cli-smoke",
        build_target="application",
        arguments=["--count", "3"],
        stdin="input\n",
        expected_exit_code=7,
        expected_stdout="done\n",
        expected_stderr="warning\n",
        timeout_ms=2_000,
        max_memory_bytes=33,
        max_output_bytes=44,
        max_file_bytes=55,
        tags=["smoke"],
        expected_revision_id="revision-base",
        author="tester",
    )

    assert response == {
        "ok": True,
        "result": {"name": "cli-smoke", "base_revision_id": "revision-base"},
    }
    assert tests.calls == [
        (
            "set",
            ("demo", "feature", "cli-smoke", "application"),
            {
                "arguments": ["--count", "3"],
                "stdin": "input\n",
                "expected_exit_code": 7,
                "expected_stdout": "done\n",
                "expected_stderr": "warning\n",
                "timeout_ms": 2_000,
                "max_memory_bytes": 33,
                "max_output_bytes": 44,
                "max_file_bytes": 55,
                "tags": ["smoke"],
                "expected_revision_id": "revision-base",
                "author": "tester",
            },
        )
    ]


def test_test_target_reads_and_delete_forward_exact_revisions(monkeypatch) -> None:
    tests = _Tests()
    monkeypatch.setattr(mcp_test_targets, "test_targets", lambda: tests)

    get_response = mcp_test_targets.test_target_get(
        "demo",
        "smoke",
        branch="feature",
        revision_id="revision-read",
    )
    list_response = mcp_test_targets.test_target_list(
        "demo",
        branch="feature",
        revision_id="revision-read",
    )
    delete_response = mcp_test_targets.test_target_delete(
        "demo",
        "smoke",
        branch="feature",
        expected_revision_id="revision-base",
        author="tester",
    )

    assert get_response["result"]["revision_id"] == "revision-read"
    assert list_response["result"] == [{"name": "smoke"}]
    assert delete_response["result"]["base_revision_id"] == "revision-base"
    assert tests.calls == [
        (
            "get",
            ("demo", "smoke"),
            {"branch": "feature", "revision_id": "revision-read"},
        ),
        (
            "list",
            ("demo",),
            {"branch": "feature", "revision_id": "revision-read"},
        ),
        (
            "delete",
            ("demo", "feature", "smoke"),
            {"expected_revision_id": "revision-base", "author": "tester"},
        ),
    ]


def test_test_capability_installs_metadata_aware_build_and_impact_services() -> None:
    assert mcp_build.BuildTargetRegistry is BuildTargetRegistry
    assert mcp_build.MergeTargetImpactService is MergeTargetImpactService
