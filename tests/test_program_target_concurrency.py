from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from weave_frontend import SExpressionWorkspace, ValidationError
from weave_frontend.concurrent_build_targets import BuildTargetRegistry

PROGRAM_A = """(program
  (name \"program-target-concurrency\")
  (version \"0.1\"))
"""
PROGRAM_B = PROGRAM_A.replace('version "0.1"', 'version "0.2"')


def _counts(workspace: SExpressionWorkspace) -> tuple[int, int]:
    revision_count = workspace.db.connection.execute(
        "SELECT COUNT(*) AS count FROM revisions"
    ).fetchone()["count"]
    operation_count = workspace.db.connection.execute(
        "SELECT COUNT(*) AS count FROM operations"
    ).fetchone()["count"]
    return int(revision_count), int(operation_count)


def test_program_create_and_import_publish_from_exact_base(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "programs.db") as workspace:
        _, initial_revision = workspace.initialize("demo")

        created = workspace.create_program(
            "demo",
            "main",
            "main.weave",
            program_name="program-target-concurrency",
            expected_revision_id=initial_revision,
        )
        assert created["base_revision_id"] == initial_revision

        imported = workspace.import_program(
            "demo",
            "main",
            "library.weave",
            PROGRAM_A,
            expected_revision_id=created["revision_id"],
        )
        assert imported["base_revision_id"] == created["revision_id"]

        replaced = workspace.import_program(
            "demo",
            "main",
            "library.weave",
            PROGRAM_B,
            replace=True,
            expected_revision_id=imported["revision_id"],
        )
        assert replaced["base_revision_id"] == imported["revision_id"]
        assert workspace.branch_head("demo", "main") == replaced["revision_id"]
        assert '(version "0.2")' in workspace.render("demo", "main", "library.weave")

        operations = workspace.db.connection.execute(
            """SELECT operation_kind FROM operations
               WHERE revision_id IN (?, ?, ?)
               ORDER BY rowid""",
            (
                created["revision_id"],
                imported["revision_id"],
                replaced["revision_id"],
            ),
        ).fetchall()
        assert [row["operation_kind"] for row in operations] == [
            "create_program",
            "import_program",
            "import_program",
        ]


def test_stale_program_write_publishes_nothing(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "stale-program.db") as workspace:
        _, initial_revision = workspace.initialize("demo")
        accepted = workspace.create_program(
            "demo",
            "main",
            "main.weave",
            program_name="accepted",
            expected_revision_id=initial_revision,
        )
        counts = _counts(workspace)

        with pytest.raises(ValidationError) as raised:
            workspace.import_program(
                "demo",
                "main",
                "stale.weave",
                PROGRAM_A,
                expected_revision_id=initial_revision,
            )

        assert raised.value.code == "STALE_BRANCH_HEAD"
        assert workspace.branch_head("demo", "main") == accepted["revision_id"]
        assert _counts(workspace) == counts
        documents = workspace.list_documents("demo", "main")
        assert [item["document"] for item in documents] == ["main.weave"]
        assert documents[0]["root_node_id"] == accepted["node_id"]
        assert documents[0]["head"] == "program"


def test_unprepared_program_write_rejects_mid_call_advance(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "program-race.db"
    with (
        SExpressionWorkspace(path) as workspace,
        SExpressionWorkspace(path) as competitor,
    ):
        workspace.initialize("demo")
        program = workspace.create_program(
            "demo",
            "main",
            "main.weave",
            program_name="race",
        )
        original_commit = workspace._commit_program_mutation
        competitor_result: dict[str, Any] = {}

        def racing_commit(*args: Any, **kwargs: Any) -> str:
            competitor_result.update(
                competitor.create_form(
                    "demo",
                    "main",
                    "main.weave",
                    program["node_id"],
                    "competitor",
                )
            )
            return original_commit(*args, **kwargs)

        monkeypatch.setattr(workspace, "_commit_program_mutation", racing_commit)

        with pytest.raises(ValidationError) as raised:
            workspace.import_program(
                "demo",
                "main",
                "lost.weave",
                PROGRAM_A,
            )

        assert raised.value.code == "STALE_BRANCH_HEAD"
        assert workspace.branch_head("demo", "main") == competitor_result["revision_id"]
        assert {item["document"] for item in workspace.list_documents("demo", "main")} == {
            "main.weave"
        }
        assert (
            workspace.find_nodes("demo", "main", "main.weave", head="competitor")[0]["node_id"]
            == competitor_result["node_id"]
        )


def test_build_target_set_update_and_delete_report_exact_bases(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "targets.db") as workspace:
        workspace.initialize("demo")
        program = workspace.create_program(
            "demo",
            "main",
            "main.weave",
            program_name="targets",
        )
        targets = BuildTargetRegistry(workspace)

        created = targets.set(
            "demo",
            "main",
            "application",
            "main.weave",
            expected_revision_id=program["revision_id"],
        )
        assert created["base_revision_id"] == program["revision_id"]

        updated = targets.set(
            "demo",
            "main",
            "application",
            "main.weave",
            compiler_target="wasm32-wasi",
            expected_revision_id=created["revision_id"],
        )
        assert updated["base_revision_id"] == created["revision_id"]
        assert updated["root_node_id"] == created["root_node_id"]
        assert updated["compiler_target"] == "wasm32-wasi"

        deleted = targets.delete(
            "demo",
            "main",
            "application",
            expected_revision_id=updated["revision_id"],
        )
        assert deleted["base_revision_id"] == updated["revision_id"]
        assert workspace.branch_head("demo", "main") == deleted["revision_id"]
        assert targets.list("demo", branch="main") == []


@pytest.mark.parametrize("operation", ["set", "delete"])
def test_build_target_writes_reject_stale_prepared_base(
    tmp_path: Path,
    operation: str,
) -> None:
    with SExpressionWorkspace(tmp_path / f"stale-target-{operation}.db") as workspace:
        workspace.initialize("demo")
        program = workspace.create_program(
            "demo",
            "main",
            "main.weave",
            program_name="targets",
        )
        targets = BuildTargetRegistry(workspace)
        target = targets.set(
            "demo",
            "main",
            "application",
            "main.weave",
            expected_revision_id=program["revision_id"],
        )
        counts = _counts(workspace)

        with pytest.raises(ValidationError) as raised:
            if operation == "set":
                targets.set(
                    "demo",
                    "main",
                    "other",
                    "main.weave",
                    expected_revision_id=program["revision_id"],
                )
            else:
                targets.delete(
                    "demo",
                    "main",
                    "application",
                    expected_revision_id=program["revision_id"],
                )

        assert raised.value.code == "STALE_BRANCH_HEAD"
        assert workspace.branch_head("demo", "main") == target["revision_id"]
        assert _counts(workspace) == counts
        assert [item["name"] for item in targets.list("demo", branch="main")] == ["application"]
