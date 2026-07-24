from __future__ import annotations

import pytest

from weave_frontend import ConflictError

from .helpers import binary, call, const


def test_parallel_agents_merge_non_overlapping_symbols(workspace):
    workspace.create_branch("demo", "agent/foo")
    workspace.create_branch("demo", "agent/bar")

    workspace.upsert_function(
        "demo",
        "agent/foo",
        "app",
        {
            "kind": "fn",
            "name": "foo",
            "params": [],
            "returns": "i32",
            "body": [
                {
                    "kind": "return",
                    "value": binary("add", call("bar"), const(1)),
                }
            ],
        },
        finalize=False,
    )
    workspace.upsert_function(
        "demo",
        "agent/bar",
        "app",
        {
            "kind": "fn",
            "name": "bar",
            "params": [],
            "returns": "i32",
            "body": [{"kind": "return", "value": const(41)}],
        },
    )

    workspace.merge("demo", target_branch="main", source_branch="agent/bar")
    result = workspace.merge("demo", target_branch="main", source_branch="agent/foo")

    workspace.validate("demo", "main")
    names = {item.qualified_name for item in workspace.find_symbols("demo")}
    assert names == {"app.foo", "app.bar"}
    assert result.changed_symbols == ("app.foo",)


def test_same_symbol_changed_differently_conflicts(workspace):
    workspace.upsert_function(
        "demo",
        "main",
        "app",
        {
            "kind": "fn",
            "name": "value",
            "params": [],
            "returns": "i32",
            "body": [{"kind": "return", "value": const(0)}],
        },
    )
    workspace.create_branch("demo", "agent/a")
    workspace.create_branch("demo", "agent/b")

    workspace.upsert_function(
        "demo",
        "agent/a",
        "app",
        {
            "kind": "fn",
            "name": "value",
            "params": [],
            "returns": "i32",
            "body": [{"kind": "return", "value": const(1)}],
        },
    )
    workspace.upsert_function(
        "demo",
        "agent/b",
        "app",
        {
            "kind": "fn",
            "name": "value",
            "params": [],
            "returns": "i32",
            "body": [{"kind": "return", "value": const(2)}],
        },
    )

    workspace.merge("demo", target_branch="main", source_branch="agent/a")
    with pytest.raises(ConflictError) as error:
        workspace.merge("demo", target_branch="main", source_branch="agent/b")

    assert error.value.conflicts == ["symbol:app.value"]
