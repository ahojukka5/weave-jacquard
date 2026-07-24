from __future__ import annotations

from .helpers import binary, const, param


def test_agent_can_build_function_around_a_syntax_hole(workspace):
    workspace.create_function(
        "demo",
        "main",
        "app",
        "factorial",
        params=[{"name": "n", "type": "i32"}],
        returns="i32",
    )
    function = workspace.inspect_function("demo", "main", "app.factorial")
    hole_id = function["body"][0]["id"]

    workspace.insert_statement(
        "demo",
        "main",
        "app",
        "factorial",
        {
            "kind": "if",
            "condition": binary("le", param("n"), const(1)),
            "then": [{"kind": "return", "value": const(1)}],
            "else": [],
        },
        before_node_id=hole_id,
    )
    workspace.replace_node(
        "demo",
        "main",
        "app",
        hole_id,
        {
            "kind": "return",
            "value": binary(
                "mul",
                param("n"),
                {
                    "kind": "call",
                    "function": "factorial",
                    "args": [binary("sub", param("n"), const(1))],
                },
            ),
        },
    )
    workspace.finalize_function("demo", "main", "app", "factorial")

    rendered = workspace.render("demo", "main", "app")
    assert "(fn factorial" in rendered
    assert "(call factorial" in rendered
    assert "(hole statement)" not in rendered
