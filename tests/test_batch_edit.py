from __future__ import annotations

import json

import pytest

from weave_frontend.batch_edit import BatchOperationError, EditBatchExecutor
from weave_frontend.errors import ValidationError


def _program(sexpr_workspace):
    return sexpr_workspace.create_program(
        "sexpr-demo",
        "main",
        "main.weave",
        program_name="batch-demo",
    )


def _constant_operations(root_id: str) -> list[dict[str, object]]:
    return [
        {"op": "create_form", "parent": root_id, "head": "entry", "as": "entry"},
        {
            "op": "add_atom",
            "parent": "@entry",
            "kind": "symbol",
            "value": "main",
            "as": "entry_name",
        },
        {"op": "create_form", "parent": "@entry", "head": "params", "as": "params"},
        {
            "op": "create_form",
            "parent": "@entry",
            "head": "returns",
            "as": "returns",
        },
        {
            "op": "add_atom",
            "parent": "@returns",
            "kind": "symbol",
            "value": "i32",
        },
        {"op": "create_form", "parent": "@entry", "head": "do", "as": "body"},
        {"op": "create_form", "parent": "@body", "head": "return", "as": "return"},
        {
            "op": "create_form",
            "parent": "@return",
            "head": "const_i32",
            "as": "constant",
        },
        {
            "op": "add_atom",
            "parent": "@constant",
            "kind": "integer",
            "value": 42,
        },
    ]


def test_batch_commits_one_revision_with_ordered_audit_rows(sexpr_workspace):
    created = _program(sexpr_workspace)
    base = sexpr_workspace.branch_head("sexpr-demo", "main")
    executor = EditBatchExecutor(sexpr_workspace)

    result = executor.apply(
        "sexpr-demo",
        "main",
        "main.weave",
        _constant_operations(created["node_id"]),
        expected_revision_id=base,
        message="construct main entry",
        include_operation_results=True,
    )

    assert result["base_revision_id"] == base
    assert result["operation_count"] == 9
    assert result["created_node_count"] == 9
    assert result["deleted_node_count"] == 0
    assert result["node_count"] == 23
    assert result["aliases"]["entry"].startswith("n_")
    assert len(result["operation_results"]) == 9
    assert len(sexpr_workspace.list_history("sexpr-demo", limit=10)) == 3
    assert "(return (const_i32 42))" in sexpr_workspace.render(
        "sexpr-demo", "main", "main.weave"
    )

    rows = sexpr_workspace.db.connection.execute(
        """SELECT sequence_number, operation_kind, payload_json
           FROM operations WHERE revision_id = ? ORDER BY sequence_number""",
        (result["revision_id"],),
    ).fetchall()
    assert [row["sequence_number"] for row in rows] == list(range(9))
    assert [row["operation_kind"] for row in rows] == [
        "create_form",
        "add_atom",
        "create_form",
        "create_form",
        "add_atom",
        "create_form",
        "create_form",
        "create_form",
        "add_atom",
    ]
    assert [json.loads(row["payload_json"])["batch_index"] for row in rows] == list(
        range(9)
    )


def test_batch_failure_rolls_back_all_prior_operations(sexpr_workspace):
    created = _program(sexpr_workspace)
    executor = EditBatchExecutor(sexpr_workspace)
    before = sexpr_workspace.branch_head("sexpr-demo", "main")

    with pytest.raises(BatchOperationError) as captured:
        executor.apply(
            "sexpr-demo",
            "main",
            "main.weave",
            [
                {
                    "op": "create_form",
                    "parent": created["node_id"],
                    "head": "entry",
                    "as": "entry",
                },
                {
                    "op": "add_atom",
                    "parent": "@missing",
                    "kind": "symbol",
                    "value": "main",
                },
            ],
        )

    error = captured.value
    assert error.code == "UNKNOWN_BATCH_ALIAS"
    assert error.operation_index == 1
    assert error.operation == "add_atom"
    assert sexpr_workspace.branch_head("sexpr-demo", "main") == before
    assert "(entry" not in sexpr_workspace.render(
        "sexpr-demo", "main", "main.weave"
    )


def test_batch_rejects_stale_expected_revision(sexpr_workspace):
    created = _program(sexpr_workspace)
    stale = sexpr_workspace.branch_head("sexpr-demo", "main")
    sexpr_workspace.create_form(
        "sexpr-demo",
        "main",
        "main.weave",
        created["node_id"],
        "entry",
    )
    current = sexpr_workspace.branch_head("sexpr-demo", "main")

    with pytest.raises(ValidationError) as captured:
        EditBatchExecutor(sexpr_workspace).apply(
            "sexpr-demo",
            "main",
            "main.weave",
            [
                {
                    "op": "create_form",
                    "parent": created["node_id"],
                    "head": "fn",
                }
            ],
            expected_revision_id=stale,
        )

    assert captured.value.code == "STALE_REVISION"
    assert sexpr_workspace.branch_head("sexpr-demo", "main") == current
