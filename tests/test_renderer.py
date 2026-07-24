from __future__ import annotations

from .helpers import const


def test_rendering_is_deterministic(workspace):
    workspace.upsert_function(
        "demo",
        "main",
        "app",
        {
            "kind": "fn",
            "name": "answer",
            "params": [],
            "returns": "i32",
            "body": [{"kind": "return", "value": const(42)}],
        },
    )

    first = workspace.render("demo", "main", "app")
    second = workspace.render("demo", "main", "app")
    assert first == second
    assert '(name "app")' in first
    assert "(return (const_i32 42))" in first
