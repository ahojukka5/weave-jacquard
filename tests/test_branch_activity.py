from __future__ import annotations

import pytest

from weave_frontend.batch_edit import EditBatchExecutor
from weave_frontend.branch_activity import BranchActivityService
from weave_frontend.errors import ValidationError


def _constant_operations(root_id: str) -> list[dict[str, object]]:
    return [
        {"op": "create_form", "parent": root_id, "head": "entry", "as": "entry"},
        {
            "op": "add_atom",
            "parent": "@entry",
            "kind": "symbol",
            "value": "main",
        },
        {"op": "create_form", "parent": "@entry", "head": "params"},
        {"op": "create_form", "parent": "@entry", "head": "returns", "as": "returns"},
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


def _build_history(sexpr_workspace):
    initialized = sexpr_workspace.branch_head("sexpr-demo", "main")
    created = sexpr_workspace.create_program(
        "sexpr-demo",
        "main",
        "main.weave",
        program_name="activity-demo",
    )
    batched = EditBatchExecutor(sexpr_workspace).apply(
        "sexpr-demo",
        "main",
        "main.weave",
        _constant_operations(created["node_id"]),
        expected_revision_id=created["revision_id"],
        message="construct main",
    )
    return initialized, created, batched


def test_history_page_has_explicit_continuation_and_operation_metadata(
    sexpr_workspace,
):
    initialized, created, batched = _build_history(sexpr_workspace)
    activity = BranchActivityService(sexpr_workspace)

    first = activity.history_page("sexpr-demo", limit=2)

    assert first["branch_head_revision_id"] == batched["revision_id"]
    assert first["returned_count"] == 2
    assert first["has_more"] is True
    assert first["next_revision_id"] == initialized
    assert [revision["id"] for revision in first["revisions"]] == [
        batched["revision_id"],
        created["revision_id"],
    ]
    assert first["revisions"][0]["operation_count"] == 9
    assert first["revisions"][0]["operation_kinds"] == [
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
    assert first["revisions"][1]["operation_kinds"] == ["create_program"]

    second = activity.history_page(
        "sexpr-demo",
        start_revision_id=first["next_revision_id"],
        limit=2,
    )
    assert second["returned_count"] == 1
    assert second["has_more"] is False
    assert second["next_revision_id"] is None
    assert second["revisions"][0]["id"] == initialized
    assert second["revisions"][0]["operation_count"] == 0


def test_activity_summary_measures_grouping_and_operation_kinds(sexpr_workspace):
    _, _, batched = _build_history(sexpr_workspace)

    summary = BranchActivityService(sexpr_workspace).summary("sexpr-demo")

    assert summary["head_revision_id"] == batched["revision_id"]
    assert summary["revision_count"] == 3
    assert summary["first_parent_edge_count"] == 2
    assert summary["merge_revision_count"] == 0
    assert summary["operation_count"] == 10
    assert summary["mutation_revision_count"] == 2
    assert summary["zero_operation_revision_count"] == 1
    assert summary["single_operation_revision_count"] == 1
    assert summary["multi_operation_revision_count"] == 1
    assert summary["max_operations_per_revision"] == 9
    assert summary["average_operations_per_mutation_revision"] == 5.0
    assert summary["revision_count_avoided_by_grouping"] == 8
    assert summary["operation_kind_counts"] == {
        "add_atom": 3,
        "create_form": 6,
        "create_program": 1,
    }
    assert sum(summary["author_revision_counts"].values()) == 3


def test_history_page_rejects_invalid_limits(sexpr_workspace):
    activity = BranchActivityService(sexpr_workspace)

    for limit in (0, 201, True):
        with pytest.raises(ValidationError) as captured:
            activity.history_page("sexpr-demo", limit=limit)
        assert captured.value.code == "INVALID_HISTORY_LIMIT"


def test_history_page_rejects_revision_from_another_branch(sexpr_workspace):
    created = sexpr_workspace.create_program(
        "sexpr-demo",
        "main",
        "main.weave",
        program_name="activity-demo",
    )
    sexpr_workspace.create_branch("sexpr-demo", "feature", from_branch="main")
    feature = sexpr_workspace.create_form(
        "sexpr-demo",
        "feature",
        "main.weave",
        created["node_id"],
        "fn",
    )

    with pytest.raises(ValidationError) as captured:
        BranchActivityService(sexpr_workspace).history_page(
            "sexpr-demo",
            "main",
            start_revision_id=feature["revision_id"],
        )

    assert captured.value.code == "REVISION_NOT_REACHABLE"
