from __future__ import annotations

import pytest

from weave_frontend import ValidationError

from .helpers import binary, const, param


def test_complete_function_is_validated_and_committed(workspace):
    result = workspace.upsert_function(
        "demo",
        "main",
        "app",
        {
            "kind": "fn",
            "name": "gcd",
            "params": [{"name": "a", "type": "i32"}, {"name": "b", "type": "i32"}],
            "returns": "i32",
            "body": [
                {
                    "kind": "while",
                    "condition": binary("ne", param("b"), const(0)),
                    "body": [
                        {
                            "kind": "let",
                            "name": "next",
                            "type": "i32",
                            "value": binary("mod", param("a"), param("b")),
                        },
                        {"kind": "return", "value": param("a")},
                    ],
                },
                {"kind": "return", "value": param("a")},
            ],
        },
    )
    assert result.created_node_ids
    assert workspace.find_symbols("demo", name="gcd")[0].signature == "(i32, i32) -> i32"


def test_invalid_statement_is_rejected_without_advancing_branch(workspace):
    draft = workspace.create_function(
        "demo", "main", "app", "foo", params=[], returns="i32"
    )
    head_before = workspace.branch_head("demo")
    hole_id = workspace.inspect_function("demo", "main", "app.foo")["body"][0]["id"]

    with pytest.raises(ValidationError) as error:
        workspace.replace_node(
            "demo",
            "main",
            "app",
            hole_id,
            {"kind": "while", "body": []},
        )

    assert error.value.code == "MISSING_FIELD"
    assert workspace.branch_head("demo") == head_before == draft.revision_id


def test_semantic_type_error_is_reported_at_finalize(workspace):
    workspace.upsert_function(
        "demo",
        "main",
        "app",
        {
            "kind": "fn",
            "name": "bad",
            "params": [],
            "returns": "i32",
            "body": [
                {
                    "kind": "return",
                    "value": {"kind": "const", "type": "bool", "value": True},
                }
            ],
        },
        finalize=False,
    )

    with pytest.raises(ValidationError) as error:
        workspace.finalize_function("demo", "main", "app", "bad")

    assert error.value.code == "TYPE_MISMATCH"
