from __future__ import annotations

import pytest

from weave_frontend import ValidationError


def test_program_can_be_built_one_form_and_atom_at_a_time(sexpr_workspace):
    created = sexpr_workspace.create_program(
        "sexpr-demo",
        "main",
        "fib.weave",
        program_name="fibonacci",
    )
    root = created["node_id"]

    entry = sexpr_workspace.create_form("sexpr-demo", "main", "fib.weave", root, "entry")
    sexpr_workspace.add_atom(
        "sexpr-demo",
        "main",
        "fib.weave",
        entry["node_id"],
        "symbol",
        "main",
    )

    function = sexpr_workspace.create_form("sexpr-demo", "main", "fib.weave", root, "fn")
    fn_id = function["node_id"]
    sexpr_workspace.add_atom("sexpr-demo", "main", "fib.weave", fn_id, "symbol", "main")
    params = sexpr_workspace.create_form("sexpr-demo", "main", "fib.weave", fn_id, "params")
    returns = sexpr_workspace.create_form("sexpr-demo", "main", "fib.weave", fn_id, "returns")
    sexpr_workspace.add_atom(
        "sexpr-demo",
        "main",
        "fib.weave",
        returns["node_id"],
        "symbol",
        "i32",
    )
    body = sexpr_workspace.create_form("sexpr-demo", "main", "fib.weave", fn_id, "do")
    ret = sexpr_workspace.create_form("sexpr-demo", "main", "fib.weave", body["node_id"], "return")
    const = sexpr_workspace.create_form(
        "sexpr-demo", "main", "fib.weave", ret["node_id"], "const_i32"
    )
    sexpr_workspace.add_atom(
        "sexpr-demo",
        "main",
        "fib.weave",
        const["node_id"],
        "integer",
        42,
    )

    source = sexpr_workspace.render("sexpr-demo", "main", "fib.weave")
    annotated = sexpr_workspace.render(
        "sexpr-demo",
        "main",
        "fib.weave",
        annotated=True,
        annotate_atoms=True,
    )

    assert "(entry main)" in source
    assert "(return (const_i32 42))" in source
    assert f"@{params['node_id']}" in annotated
    assert f"@{const['node_id']}" in annotated


def test_invalid_atomic_write_does_not_advance_branch(sexpr_workspace):
    created = sexpr_workspace.create_program(
        "sexpr-demo",
        "main",
        "main.weave",
        program_name="sexpr-demo",
    )
    before = sexpr_workspace.branch_head("sexpr-demo", "main")

    with pytest.raises(ValidationError):
        sexpr_workspace.add_atom(
            "sexpr-demo",
            "main",
            "main.weave",
            created["node_id"],
            "banana",
            "x",
        )

    assert sexpr_workspace.branch_head("sexpr-demo", "main") == before


def test_node_inspection_returns_local_id_bearing_view(sexpr_workspace):
    created = sexpr_workspace.create_program(
        "sexpr-demo",
        "main",
        "main.weave",
        program_name="sexpr-demo",
    )
    function = sexpr_workspace.create_form(
        "sexpr-demo",
        "main",
        "main.weave",
        created["node_id"],
        "fn",
    )

    inspected = sexpr_workspace.inspect_node(
        "sexpr-demo",
        "main",
        "main.weave",
        function["node_id"],
        depth=2,
    )
    assert inspected["node_id"] == function["node_id"]
    assert f"@{function['node_id']}" in inspected["annotated_weave"]
