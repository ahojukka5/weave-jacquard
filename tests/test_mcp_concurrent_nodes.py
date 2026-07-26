from __future__ import annotations

from typing import Any

import pytest

from weave_frontend import mcp_concurrent_nodes
from weave_frontend.concurrent_sexpr import SExpressionWorkspace
from weave_frontend.errors import ValidationError


class _Workspace:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _call(self, name: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((name, args, kwargs))
        return {
            "revision_id": "revision-new",
            "base_revision_id": kwargs.get("expected_revision_id") or "revision-base",
            "node_id": "n_result",
        }

    def create_form(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self._call("create_form", *args, **kwargs)

    def add_atom(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self._call("add_atom", *args, **kwargs)

    def set_atom(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self._call("set_atom", *args, **kwargs)

    def delete_node(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self._call("delete_node", *args, **kwargs)

    def move_node(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self._call("move_node", *args, **kwargs)

    def wrap_node(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self._call("wrap_node", *args, **kwargs)


@pytest.mark.parametrize(
    ("tool", "arguments", "method", "positional"),
    [
        (
            mcp_concurrent_nodes.node_create_form,
            {
                "project": "demo",
                "branch": "main",
                "document": "main.weave",
                "parent_id": "n_parent",
                "head": "do",
                "position": 2,
            },
            "create_form",
            ("demo", "main", "main.weave", "n_parent", "do"),
        ),
        (
            mcp_concurrent_nodes.node_add_atom,
            {
                "project": "demo",
                "branch": "main",
                "document": "main.weave",
                "parent_id": "n_parent",
                "kind": "integer",
                "value": 4,
                "position": 1,
            },
            "add_atom",
            ("demo", "main", "main.weave", "n_parent", "integer", 4),
        ),
        (
            mcp_concurrent_nodes.node_set_atom,
            {
                "project": "demo",
                "branch": "main",
                "document": "main.weave",
                "node_id": "n_atom",
                "value": 5,
            },
            "set_atom",
            ("demo", "main", "main.weave", "n_atom", 5),
        ),
        (
            mcp_concurrent_nodes.node_delete,
            {
                "project": "demo",
                "branch": "main",
                "document": "main.weave",
                "node_id": "n_delete",
            },
            "delete_node",
            ("demo", "main", "main.weave", "n_delete"),
        ),
        (
            mcp_concurrent_nodes.node_move,
            {
                "project": "demo",
                "branch": "main",
                "document": "main.weave",
                "node_id": "n_move",
                "new_parent_id": "n_destination",
                "position": 3,
            },
            "move_node",
            ("demo", "main", "main.weave", "n_move", "n_destination"),
        ),
        (
            mcp_concurrent_nodes.node_wrap,
            {
                "project": "demo",
                "branch": "main",
                "document": "main.weave",
                "node_id": "n_wrap",
                "head": "return",
            },
            "wrap_node",
            ("demo", "main", "main.weave", "n_wrap", "return"),
        ),
    ],
)
def test_node_tools_forward_expected_revision(
    monkeypatch,
    tool,
    arguments: dict[str, Any],
    method: str,
    positional: tuple[Any, ...],
) -> None:
    workspace = _Workspace()
    monkeypatch.setattr(mcp_concurrent_nodes, "workspace", lambda: workspace)

    response = tool(**arguments, expected_revision_id="revision-base")

    assert response["ok"] is True
    assert response["result"]["base_revision_id"] == "revision-base"
    assert workspace.calls[0][0] == method
    assert workspace.calls[0][1] == positional
    assert workspace.calls[0][2]["expected_revision_id"] == "revision-base"
    if "position" in arguments:
        assert workspace.calls[0][2]["position"] == arguments["position"]


def test_node_tool_returns_structured_stale_error(monkeypatch) -> None:
    class _Stale:
        def set_atom(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            raise ValidationError("STALE_BRANCH_HEAD", "branch advanced")

    monkeypatch.setattr(mcp_concurrent_nodes, "workspace", lambda: _Stale())

    response = mcp_concurrent_nodes.node_set_atom(
        "demo",
        "main",
        "main.weave",
        "n_atom",
        2,
        expected_revision_id="revision-old",
    )

    assert response["ok"] is False
    assert response["error"] == {
        "code": "STALE_BRANCH_HEAD",
        "message": "branch advanced",
    }


def test_production_workspace_factory_uses_race_safe_subclass(tmp_path, monkeypatch) -> None:
    mcp_concurrent_nodes.workspace.cache_clear()
    monkeypatch.setenv("WEAVE_DB_PATH", str(tmp_path / "mcp.db"))
    value = mcp_concurrent_nodes.workspace()
    try:
        assert isinstance(value, SExpressionWorkspace)
    finally:
        value.close()
        mcp_concurrent_nodes.workspace.cache_clear()
