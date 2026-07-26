from __future__ import annotations

from typing import Any

import pytest

from weave_frontend import mcp_concurrent_nodes, mcp_concurrent_targets


class _Workspace:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def create_program(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("create_program", args, kwargs))
        return {
            "revision_id": "revision-new",
            "base_revision_id": kwargs["expected_revision_id"],
            "node_id": "n_program",
        }

    def import_program(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("import_program", args, kwargs))
        return {
            "revision_id": "revision-new",
            "base_revision_id": kwargs["expected_revision_id"],
            "node_id": "n_program",
        }


class _Targets:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def set(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("set", args, kwargs))
        return {
            "revision_id": "revision-new",
            "base_revision_id": kwargs["expected_revision_id"],
            "name": args[2],
        }

    def delete(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("delete", args, kwargs))
        return {
            "revision_id": "revision-new",
            "base_revision_id": kwargs["expected_revision_id"],
            "name": args[2],
        }


@pytest.mark.parametrize(
    ("tool", "arguments", "method", "positional", "keywords"),
    [
        (
            mcp_concurrent_nodes.program_create,
            {
                "project": "demo",
                "branch": "main",
                "document": "main.weave",
                "program_name": "demo",
                "version": "2.0",
            },
            "create_program",
            ("demo", "main", "main.weave"),
            {"program_name": "demo", "version": "2.0"},
        ),
        (
            mcp_concurrent_nodes.program_import,
            {
                "project": "demo",
                "branch": "main",
                "document": "main.weave",
                "source": "(program)",
                "replace": True,
            },
            "import_program",
            ("demo", "main", "main.weave", "(program)"),
            {"replace": True},
        ),
    ],
)
def test_program_tools_forward_expected_revision(
    monkeypatch,
    tool,
    arguments: dict[str, Any],
    method: str,
    positional: tuple[Any, ...],
    keywords: dict[str, Any],
) -> None:
    workspace = _Workspace()
    monkeypatch.setattr(mcp_concurrent_nodes, "workspace", lambda: workspace)

    response = tool(**arguments, expected_revision_id="revision-base")

    assert response["ok"] is True
    assert response["result"]["base_revision_id"] == "revision-base"
    assert workspace.calls == [
        (
            method,
            positional,
            {**keywords, "expected_revision_id": "revision-base"},
        )
    ]


@pytest.mark.parametrize(
    ("tool", "arguments", "method", "positional", "keywords"),
    [
        (
            mcp_concurrent_targets.build_target_set,
            {
                "project": "demo",
                "name": "application",
                "document": "main.weave",
                "branch": "feature",
                "additional_documents": ["lib.weave"],
                "compiler_target": "wasm32-wasi",
            },
            "set",
            ("demo", "feature", "application", "main.weave"),
            {
                "additional_documents": ["lib.weave"],
                "compiler_target": "wasm32-wasi",
            },
        ),
        (
            mcp_concurrent_targets.build_target_delete,
            {
                "project": "demo",
                "name": "application",
                "branch": "feature",
            },
            "delete",
            ("demo", "feature", "application"),
            {},
        ),
    ],
)
def test_target_tools_forward_expected_revision(
    monkeypatch,
    tool,
    arguments: dict[str, Any],
    method: str,
    positional: tuple[Any, ...],
    keywords: dict[str, Any],
) -> None:
    targets = _Targets()
    monkeypatch.setattr(mcp_concurrent_targets, "build_targets", lambda: targets)

    response = tool(**arguments, expected_revision_id="revision-base")

    assert response["ok"] is True
    assert response["result"]["base_revision_id"] == "revision-base"
    assert targets.calls == [
        (
            method,
            positional,
            {**keywords, "expected_revision_id": "revision-base"},
        )
    ]
