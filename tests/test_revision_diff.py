from __future__ import annotations

from typing import Any

import pytest

from weave_frontend.errors import NotFoundError, ValidationError
from weave_frontend.revision_diff import RevisionNodeDiffService


def _changed_workspace(sexpr_workspace):
    created = sexpr_workspace.create_program(
        "sexpr-demo",
        "main",
        "main.weave",
        program_name="revision-diff",
    )
    left = sexpr_workspace.create_form(
        "sexpr-demo", "main", "main.weave", created["node_id"], "left"
    )
    right = sexpr_workspace.create_form(
        "sexpr-demo", "main", "main.weave", created["node_id"], "right"
    )
    number = sexpr_workspace.add_atom(
        "sexpr-demo", "main", "main.weave", left["node_id"], "integer", 1
    )
    removed = sexpr_workspace.add_atom(
        "sexpr-demo", "main", "main.weave", left["node_id"], "string", "remove"
    )
    base_revision = removed["revision_id"]

    sexpr_workspace.set_atom(
        "sexpr-demo", "main", "main.weave", number["node_id"], 2
    )
    added = sexpr_workspace.add_atom(
        "sexpr-demo", "main", "main.weave", right["node_id"], "boolean", True
    )
    sexpr_workspace.move_node(
        "sexpr-demo",
        "main",
        "main.weave",
        number["node_id"],
        right["node_id"],
    )
    target = sexpr_workspace.delete_node(
        "sexpr-demo", "main", "main.weave", removed["node_id"]
    )
    return {
        "base_revision": base_revision,
        "target_revision": target["revision_id"],
        "left_id": left["node_id"],
        "right_id": right["node_id"],
        "number_id": number["node_id"],
        "added_id": added["node_id"],
        "removed_id": removed["node_id"],
    }


def test_revision_diff_pages_exact_stable_node_changes(sexpr_workspace) -> None:
    values = _changed_workspace(sexpr_workspace)
    service = RevisionNodeDiffService(sexpr_workspace)

    first = service.page(
        "sexpr-demo",
        "main.weave",
        values["base_revision"],
        limit=2,
    )
    second = service.page(
        "sexpr-demo",
        "main.weave",
        values["base_revision"],
        start_index=first["next_index"],
        limit=2,
    )
    third = service.page(
        "sexpr-demo",
        "main.weave",
        values["base_revision"],
        start_index=second["next_index"],
        limit=2,
    )

    changes = first["changes"] + second["changes"] + third["changes"]
    by_id = {change["node_id"]: change for change in changes}
    assert len(changes) == len(by_id) == 5
    assert first["total_change_count"] == 5
    assert first["target_revision_id"] == values["target_revision"]
    assert first["target_revision_is_branch_head"] is True
    assert first["next_index"] == 2
    assert second["next_index"] == 4
    assert third["has_more"] is False
    assert third["next_index"] is None

    assert by_id[values["left_id"]]["change_kinds"] == ["child_count_changed"]
    assert by_id[values["right_id"]]["change_kinds"] == ["child_count_changed"]
    assert by_id[values["number_id"]]["change_kinds"] == [
        "value_changed",
        "parent_changed",
        "position_changed",
    ]
    assert by_id[values["number_id"]]["before"]["value"] == 1
    assert by_id[values["number_id"]]["after"]["value"] == 2
    assert by_id[values["number_id"]]["before"]["parent_id"] == values["left_id"]
    assert by_id[values["number_id"]]["after"]["parent_id"] == values["right_id"]
    assert by_id[values["added_id"]]["change_kinds"] == ["added"]
    assert by_id[values["added_id"]]["before"] is None
    assert by_id[values["removed_id"]]["change_kinds"] == ["removed"]
    assert by_id[values["removed_id"]]["after"] is None
    assert first["change_kind_counts"] == {
        "added": 1,
        "child_count_changed": 2,
        "parent_changed": 1,
        "position_changed": 1,
        "removed": 1,
        "value_changed": 1,
    }


def test_revision_diff_supports_explicit_non_head_target(sexpr_workspace) -> None:
    values = _changed_workspace(sexpr_workspace)
    service = RevisionNodeDiffService(sexpr_workspace)
    branch_head = sexpr_workspace.branch_head("sexpr-demo", "main")

    same = service.page(
        "sexpr-demo",
        "main.weave",
        values["base_revision"],
        target_revision_id=values["base_revision"],
    )

    assert same["branch_head_revision_id"] == branch_head
    assert same["target_revision_id"] == values["base_revision"]
    assert same["target_revision_is_branch_head"] is False
    assert same["total_change_count"] == 0
    assert same["changes"] == []
    assert same["change_kind_counts"] == {}


def test_revision_diff_reports_document_addition_and_removal(sexpr_workspace) -> None:
    empty_revision = sexpr_workspace.branch_head("sexpr-demo", "main")
    created = sexpr_workspace.create_program(
        "sexpr-demo", "main", "new.weave", program_name="new"
    )
    service = RevisionNodeDiffService(sexpr_workspace)

    added = service.page(
        "sexpr-demo",
        "new.weave",
        empty_revision,
        target_revision_id=created["revision_id"],
        limit=200,
    )
    removed = service.page(
        "sexpr-demo",
        "new.weave",
        created["revision_id"],
        target_revision_id=empty_revision,
        limit=200,
    )

    assert added["base_document_present"] is False
    assert added["target_document_present"] is True
    assert added["total_change_count"] == added["target_node_count"]
    assert {kind for change in added["changes"] for kind in change["change_kinds"]} == {
        "added"
    }
    assert removed["base_document_present"] is True
    assert removed["target_document_present"] is False
    assert removed["total_change_count"] == removed["base_node_count"]
    assert {
        kind for change in removed["changes"] for kind in change["change_kinds"]
    } == {"removed"}


def test_revision_diff_rejects_foreign_revisions_and_missing_documents(
    sexpr_workspace,
) -> None:
    created = sexpr_workspace.create_program(
        "sexpr-demo", "main", "main.weave", program_name="demo"
    )
    sexpr_workspace.initialize("other-project")
    foreign_revision = sexpr_workspace.branch_head("other-project", "main")
    service = RevisionNodeDiffService(sexpr_workspace)

    with pytest.raises(NotFoundError, match="does not belong"):
        service.page(
            "sexpr-demo",
            "main.weave",
            foreign_revision,
            target_revision_id=created["revision_id"],
        )
    with pytest.raises(NotFoundError, match="does not belong"):
        service.page(
            "sexpr-demo",
            "main.weave",
            created["revision_id"],
            target_revision_id=foreign_revision,
        )
    with pytest.raises(NotFoundError, match="absent from revisions"):
        service.page(
            "sexpr-demo",
            "missing.weave",
            created["revision_id"],
            target_revision_id=created["revision_id"],
        )


@pytest.mark.parametrize("value", [-1, True, 1.5, "0"])
def test_revision_diff_rejects_invalid_start_index(
    sexpr_workspace,
    value: Any,
) -> None:
    created = sexpr_workspace.create_program(
        "sexpr-demo", "main", "main.weave", program_name="demo"
    )
    service = RevisionNodeDiffService(sexpr_workspace)

    with pytest.raises(ValidationError, match="start_index") as captured:
        service.page(
            "sexpr-demo",
            "main.weave",
            created["revision_id"],
            start_index=value,
        )
    assert captured.value.code == "INVALID_REVISION_DIFF_INDEX"


@pytest.mark.parametrize("value", [0, 201, True, 1.5, "1"])
def test_revision_diff_rejects_invalid_limit(
    sexpr_workspace,
    value: Any,
) -> None:
    created = sexpr_workspace.create_program(
        "sexpr-demo", "main", "main.weave", program_name="demo"
    )
    service = RevisionNodeDiffService(sexpr_workspace)

    with pytest.raises(ValidationError, match="limit") as captured:
        service.page(
            "sexpr-demo",
            "main.weave",
            created["revision_id"],
            limit=value,
        )
    assert captured.value.code == "INVALID_REVISION_DIFF_LIMIT"
