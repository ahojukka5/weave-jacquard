from __future__ import annotations


def test_parallel_agents_can_append_different_forms_and_merge(sexpr_workspace):
    program = sexpr_workspace.create_program(
        "sexpr-demo",
        "main",
        "main.weave",
        program_name="parallel",
    )
    root_id = program["node_id"]
    sexpr_workspace.create_branch("sexpr-demo", "agent/foo")
    sexpr_workspace.create_branch("sexpr-demo", "agent/bar")

    foo = sexpr_workspace.create_form(
        "sexpr-demo", "agent/foo", "main.weave", root_id, "fn"
    )
    sexpr_workspace.add_atom(
        "sexpr-demo",
        "agent/foo",
        "main.weave",
        foo["node_id"],
        "symbol",
        "foo",
    )

    bar = sexpr_workspace.create_form(
        "sexpr-demo", "agent/bar", "main.weave", root_id, "fn"
    )
    sexpr_workspace.add_atom(
        "sexpr-demo",
        "agent/bar",
        "main.weave",
        bar["node_id"],
        "symbol",
        "bar",
    )

    sexpr_workspace.merge(
        "sexpr-demo",
        target_branch="main",
        source_branch="agent/foo",
    )
    sexpr_workspace.merge(
        "sexpr-demo",
        target_branch="main",
        source_branch="agent/bar",
    )

    source = sexpr_workspace.render("sexpr-demo", "main", "main.weave")
    assert "(fn foo)" in source
    assert "(fn bar)" in source
