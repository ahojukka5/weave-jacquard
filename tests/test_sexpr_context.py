from __future__ import annotations


def test_context_is_versioned_with_branch(sexpr_workspace):
    sexpr_workspace.create_program(
        "sexpr-demo",
        "main",
        "main.weave",
        program_name="sexpr-demo",
    )
    sexpr_workspace.add_context(
        "sexpr-demo",
        "main",
        scope_kind="document",
        scope_name="main.weave",
        title="Interface rule",
        body="Public functions return i32.",
    )

    context = sexpr_workspace.get_context(
        "sexpr-demo",
        "main",
        scope_name="main.weave",
    )
    assert context[0]["title"] == "Interface rule"


def test_validation_reports_missing_weavec_without_guessing(sexpr_workspace):
    sexpr_workspace.create_program(
        "sexpr-demo",
        "main",
        "main.weave",
        program_name="sexpr-demo",
    )
    sexpr_workspace.validator.binary = None
    result = sexpr_workspace.validate_program(
        "sexpr-demo",
        "main",
        "main.weave",
    )

    assert result["structurally_valid"] is True
    assert result["available"] is False
    assert result["valid"] is None
