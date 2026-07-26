from __future__ import annotations

import pytest

from weave_frontend import NotFoundError
from weave_frontend.revision_inspection import RevisionNodeInspectionService


def test_inspection_defaults_to_branch_head_and_can_pin_history(sexpr_workspace) -> None:
    created = sexpr_workspace.create_program(
        "sexpr-demo",
        "main",
        "main.weave",
        program_name="revision-inspection",
    )
    atom = sexpr_workspace.add_atom(
        "sexpr-demo",
        "main",
        "main.weave",
        created["node_id"],
        "symbol",
        "before",
    )
    historical_revision = str(atom["revision_id"])
    repaired = sexpr_workspace.set_atom(
        "sexpr-demo",
        "main",
        "main.weave",
        atom["node_id"],
        "after",
    )
    current_revision = str(repaired["revision_id"])
    service = RevisionNodeInspectionService(sexpr_workspace)

    current = service.inspect(
        "sexpr-demo",
        "main",
        "main.weave",
        atom["node_id"],
    )
    historical = service.inspect(
        "sexpr-demo",
        "main",
        "main.weave",
        atom["node_id"],
        revision_id=historical_revision,
    )

    assert current["revision_id"] == current_revision
    assert current["branch_head_revision_id"] == current_revision
    assert current["revision_is_branch_head"] is True
    assert current["subtree"]["value"] == "after"

    assert historical["revision_id"] == historical_revision
    assert historical["branch_head_revision_id"] == current_revision
    assert historical["revision_is_branch_head"] is False
    assert historical["node_id"] == current["node_id"]
    assert historical["subtree"]["value"] == "before"
    assert historical["parent_id"] == current["parent_id"]


def test_inspection_rejects_revision_from_another_project(sexpr_workspace) -> None:
    created = sexpr_workspace.create_program(
        "sexpr-demo",
        "main",
        "main.weave",
        program_name="revision-inspection",
    )
    sexpr_workspace.initialize("other-project")
    other = sexpr_workspace.create_program(
        "other-project",
        "main",
        "other.weave",
        program_name="other",
    )
    service = RevisionNodeInspectionService(sexpr_workspace)

    with pytest.raises(NotFoundError, match="does not belong"):
        service.inspect(
            "sexpr-demo",
            "main",
            "main.weave",
            created["node_id"],
            revision_id=other["revision_id"],
        )


def test_inspection_reports_node_absent_from_older_revision(sexpr_workspace) -> None:
    created = sexpr_workspace.create_program(
        "sexpr-demo",
        "main",
        "main.weave",
        program_name="revision-inspection",
    )
    before_node = str(created["revision_id"])
    added = sexpr_workspace.add_atom(
        "sexpr-demo",
        "main",
        "main.weave",
        created["node_id"],
        "symbol",
        "later",
    )
    service = RevisionNodeInspectionService(sexpr_workspace)

    with pytest.raises(NotFoundError, match=str(added["node_id"])):
        service.inspect(
            "sexpr-demo",
            "main",
            "main.weave",
            added["node_id"],
            revision_id=before_node,
        )
