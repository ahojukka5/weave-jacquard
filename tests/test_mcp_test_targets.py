from __future__ import annotations

from typing import Any

from weave_frontend import mcp_build, mcp_test_targets, selected_merge_train_preview
from weave_frontend.metadata_build_targets import BuildTargetRegistry
from weave_frontend.metadata_merge_impact import MergeTargetImpactService
from weave_frontend.metadata_merge_preview import MergePreviewService
from weave_frontend.metadata_selected_merge_train_preview import (
    SelectedMergeTrainPreviewService,
)


class _Tests:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def set(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("set", args, kwargs))
        return {
            "name": args[2],
            "base_revision_id": kwargs["expected_revision_id"],
            "definition_hash": "definition-hash",
        }

    def get(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("get", args, kwargs))
        return {
            "name": args[1],
            "revision_id": kwargs["revision_id"],
            "definition_hash": "definition-hash",
        }

    def delete(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("delete", args, kwargs))
        return {"name": args[2], "base_revision_id": kwargs["expected_revision_id"]}


class _Pages:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def page(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((args, kwargs))
        return {
            "format": "weave-test-target-list-v1",
            "revision_id": kwargs["revision_id"],
            "test_targets": [{"name": "smoke"}],
        }


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
        "result": {
            "name": "cli-smoke",
            "base_revision_id": "revision-base",
            "definition_hash": "definition-hash",
        },
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


def test_test_target_reads_list_page_and_delete_forward_exact_state(monkeypatch) -> None:
    tests = _Tests()
    pages = _Pages()
    monkeypatch.setattr(mcp_test_targets, "test_targets", lambda: tests)
    monkeypatch.setattr(mcp_test_targets, "test_target_pages", lambda: pages)

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
        start_after_name="alpha",
        limit=25,
    )
    delete_response = mcp_test_targets.test_target_delete(
        "demo",
        "smoke",
        branch="feature",
        expected_revision_id="revision-base",
        author="tester",
    )

    assert get_response["result"]["revision_id"] == "revision-read"
    assert get_response["result"]["definition_hash"] == "definition-hash"
    assert list_response["result"]["test_targets"] == [{"name": "smoke"}]
    assert delete_response["result"]["base_revision_id"] == "revision-base"
    assert tests.calls == [
        (
            "get",
            ("demo", "smoke"),
            {"branch": "feature", "revision_id": "revision-read"},
        ),
        (
            "delete",
            ("demo", "feature", "smoke"),
            {"expected_revision_id": "revision-base", "author": "tester"},
        ),
    ]
    assert pages.calls == [
        (
            ("demo",),
            {
                "branch": "feature",
                "revision_id": "revision-read",
                "start_after_name": "alpha",
                "limit": 25,
            },
        )
    ]


def test_metadata_aware_merge_services_install_explicitly() -> None:
    mcp_test_targets.install_metadata_aware_merge_services()

    assert mcp_build.BuildTargetRegistry is BuildTargetRegistry
    assert mcp_build.MergePreviewService is MergePreviewService
    assert mcp_build.MergeTargetImpactService is MergeTargetImpactService
    assert (
        selected_merge_train_preview.SelectedMergeTrainPreviewService
        is SelectedMergeTrainPreviewService
    )
