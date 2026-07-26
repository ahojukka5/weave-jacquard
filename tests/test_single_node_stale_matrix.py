from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest

from weave_frontend import SExpressionWorkspace, ValidationError

Mutation = Callable[[SExpressionWorkspace, dict[str, Any], str], dict[str, Any]]


def _create_form(
    workspace: SExpressionWorkspace,
    program: dict[str, Any],
    expected: str,
) -> dict[str, Any]:
    return workspace.create_form(
        "demo",
        "main",
        "main.weave",
        program["node_id"],
        "stale-form",
        expected_revision_id=expected,
    )


def _add_atom(
    workspace: SExpressionWorkspace,
    program: dict[str, Any],
    expected: str,
) -> dict[str, Any]:
    return workspace.add_atom(
        "demo",
        "main",
        "main.weave",
        program["node_id"],
        "integer",
        1,
        expected_revision_id=expected,
    )


def _set_atom(
    workspace: SExpressionWorkspace,
    program: dict[str, Any],
    expected: str,
) -> dict[str, Any]:
    return workspace.set_atom(
        "demo",
        "main",
        "main.weave",
        "n_missing",
        1,
        expected_revision_id=expected,
    )


def _delete_node(
    workspace: SExpressionWorkspace,
    program: dict[str, Any],
    expected: str,
) -> dict[str, Any]:
    return workspace.delete_node(
        "demo",
        "main",
        "main.weave",
        "n_missing",
        expected_revision_id=expected,
    )


def _move_node(
    workspace: SExpressionWorkspace,
    program: dict[str, Any],
    expected: str,
) -> dict[str, Any]:
    return workspace.move_node(
        "demo",
        "main",
        "main.weave",
        "n_missing",
        program["node_id"],
        expected_revision_id=expected,
    )


def _wrap_node(
    workspace: SExpressionWorkspace,
    program: dict[str, Any],
    expected: str,
) -> dict[str, Any]:
    return workspace.wrap_node(
        "demo",
        "main",
        "main.weave",
        "n_missing",
        "stale-wrapper",
        expected_revision_id=expected,
    )


@pytest.mark.parametrize(
    "mutation",
    [_create_form, _add_atom, _set_atom, _delete_node, _move_node, _wrap_node],
    ids=["create-form", "add-atom", "set-atom", "delete", "move", "wrap"],
)
def test_every_single_node_tool_rejects_stale_prepared_base(
    tmp_path: Path,
    mutation: Mutation,
) -> None:
    with SExpressionWorkspace(tmp_path / f"{mutation.__name__}.db") as workspace:
        workspace.initialize("demo")
        program = workspace.create_program(
            "demo",
            "main",
            "main.weave",
            program_name="single-node-stale-matrix",
        )
        stale_base = str(program["revision_id"])
        accepted = workspace.create_form(
            "demo",
            "main",
            "main.weave",
            program["node_id"],
            "accepted",
            expected_revision_id=stale_base,
        )
        revision_count = workspace.db.connection.execute(
            "SELECT COUNT(*) AS count FROM revisions"
        ).fetchone()["count"]
        operation_count = workspace.db.connection.execute(
            "SELECT COUNT(*) AS count FROM operations"
        ).fetchone()["count"]

        with pytest.raises(ValidationError) as raised:
            mutation(workspace, program, stale_base)

        assert raised.value.code == "STALE_BRANCH_HEAD"
        assert workspace.branch_head("demo", "main") == accepted["revision_id"]
        assert workspace.db.connection.execute(
            "SELECT COUNT(*) AS count FROM revisions"
        ).fetchone()["count"] == revision_count
        assert workspace.db.connection.execute(
            "SELECT COUNT(*) AS count FROM operations"
        ).fetchone()["count"] == operation_count
