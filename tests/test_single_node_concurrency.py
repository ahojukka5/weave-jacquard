from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from weave_frontend import SExpressionWorkspace, ValidationError


def _program(workspace: SExpressionWorkspace) -> dict[str, Any]:
    return workspace.create_program(
        "demo",
        "main",
        "main.weave",
        program_name="single-node-concurrency",
    )


def test_all_single_node_mutations_report_and_advance_exact_base(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "writes.db") as workspace:
        workspace.initialize("demo")
        program = _program(workspace)
        head = str(program["revision_id"])

        left = workspace.create_form(
            "demo",
            "main",
            "main.weave",
            program["node_id"],
            "left",
            expected_revision_id=head,
        )
        assert left["base_revision_id"] == head
        head = str(left["revision_id"])

        right = workspace.create_form(
            "demo",
            "main",
            "main.weave",
            program["node_id"],
            "right",
            expected_revision_id=head,
        )
        assert right["base_revision_id"] == head
        head = str(right["revision_id"])

        atom = workspace.add_atom(
            "demo",
            "main",
            "main.weave",
            left["node_id"],
            "integer",
            1,
            expected_revision_id=head,
        )
        assert atom["base_revision_id"] == head
        head = str(atom["revision_id"])

        changed = workspace.set_atom(
            "demo",
            "main",
            "main.weave",
            atom["node_id"],
            2,
            expected_revision_id=head,
        )
        assert changed["base_revision_id"] == head
        assert changed["node_id"] == atom["node_id"]
        head = str(changed["revision_id"])

        moved = workspace.move_node(
            "demo",
            "main",
            "main.weave",
            atom["node_id"],
            right["node_id"],
            expected_revision_id=head,
        )
        assert moved["base_revision_id"] == head
        assert moved["node_id"] == atom["node_id"]
        head = str(moved["revision_id"])

        wrapped = workspace.wrap_node(
            "demo",
            "main",
            "main.weave",
            atom["node_id"],
            "wrapped",
            expected_revision_id=head,
        )
        assert wrapped["base_revision_id"] == head
        assert wrapped["wrapped_node_id"] == atom["node_id"]
        head = str(wrapped["revision_id"])

        deleted = workspace.delete_node(
            "demo",
            "main",
            "main.weave",
            wrapped["node_id"],
            expected_revision_id=head,
        )
        assert deleted["base_revision_id"] == head
        assert deleted["deleted_node_id"] == wrapped["node_id"]
        assert workspace.branch_head("demo", "main") == deleted["revision_id"]

        operations = workspace.db.connection.execute(
            """SELECT operation_kind
               FROM operations
               WHERE revision_id IN (?, ?, ?, ?, ?, ?, ?)
               ORDER BY rowid""",
            (
                left["revision_id"],
                right["revision_id"],
                atom["revision_id"],
                changed["revision_id"],
                moved["revision_id"],
                wrapped["revision_id"],
                deleted["revision_id"],
            ),
        ).fetchall()
        assert [row["operation_kind"] for row in operations] == [
            "create_form",
            "create_form",
            "add_atom",
            "set_atom",
            "move_node",
            "wrap_node",
            "delete_node",
        ]


def test_stale_prepared_node_write_publishes_nothing(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "stale.db") as workspace:
        workspace.initialize("demo")
        program = _program(workspace)
        prepared_base = str(program["revision_id"])
        accepted = workspace.create_form(
            "demo",
            "main",
            "main.weave",
            program["node_id"],
            "accepted",
            expected_revision_id=prepared_base,
        )
        revision_count = workspace.db.connection.execute(
            "SELECT COUNT(*) AS count FROM revisions"
        ).fetchone()["count"]
        operation_count = workspace.db.connection.execute(
            "SELECT COUNT(*) AS count FROM operations"
        ).fetchone()["count"]

        with pytest.raises(ValidationError) as raised:
            workspace.create_form(
                "demo",
                "main",
                "main.weave",
                program["node_id"],
                "stale",
                expected_revision_id=prepared_base,
            )

        assert raised.value.code == "STALE_BRANCH_HEAD"
        assert workspace.branch_head("demo", "main") == accepted["revision_id"]
        assert (
            workspace.db.connection.execute("SELECT COUNT(*) AS count FROM revisions").fetchone()[
                "count"
            ]
            == revision_count
        )
        assert (
            workspace.db.connection.execute("SELECT COUNT(*) AS count FROM operations").fetchone()[
                "count"
            ]
            == operation_count
        )
        assert workspace.find_nodes("demo", "main", "main.weave", head="stale") == []


@pytest.mark.parametrize("value", ["", 3, False])
def test_expected_revision_id_must_be_nonempty_string_or_null(
    tmp_path: Path,
    value: Any,
) -> None:
    with SExpressionWorkspace(tmp_path / f"invalid-{value!r}.db") as workspace:
        workspace.initialize("demo")
        program = _program(workspace)

        with pytest.raises(ValidationError) as raised:
            workspace.create_form(
                "demo",
                "main",
                "main.weave",
                program["node_id"],
                "invalid",
                expected_revision_id=value,
            )

        assert raised.value.code == "INVALID_EXPECTED_REVISION_ID"


def test_unprepared_write_rejects_mid_call_branch_advance(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "race.db"
    with (
        SExpressionWorkspace(path) as workspace,
        SExpressionWorkspace(path) as competitor,
    ):
        workspace.initialize("demo")
        program = _program(workspace)
        root_id = str(program["node_id"])
        revision_count = workspace.db.connection.execute(
            "SELECT COUNT(*) AS count FROM revisions"
        ).fetchone()["count"]
        original_commit = workspace._commit_node_mutation
        competitor_result: dict[str, Any] = {}

        def racing_commit(*args: Any, **kwargs: Any) -> str:
            competitor_result.update(
                competitor.add_atom(
                    "demo",
                    "main",
                    "main.weave",
                    root_id,
                    "integer",
                    99,
                )
            )
            return original_commit(*args, **kwargs)

        monkeypatch.setattr(workspace, "_commit_node_mutation", racing_commit)

        with pytest.raises(ValidationError) as raised:
            workspace.create_form(
                "demo",
                "main",
                "main.weave",
                root_id,
                "would-clobber",
            )

        assert raised.value.code == "STALE_BRANCH_HEAD"
        assert workspace.branch_head("demo", "main") == competitor_result["revision_id"]
        assert (
            workspace.db.connection.execute("SELECT COUNT(*) AS count FROM revisions").fetchone()[
                "count"
            ]
            == revision_count + 1
        )
        assert workspace.find_nodes("demo", "main", "main.weave", head="would-clobber") == []
        assert (
            workspace.find_nodes("demo", "main", "main.weave", value=99)[0]["node_id"]
            == competitor_result["node_id"]
        )
