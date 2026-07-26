from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from weave_frontend import NotFoundError, SExpressionWorkspace, ValidationError


def _heads(workspace: SExpressionWorkspace, project: str) -> dict[str, str]:
    return {
        str(item["name"]): str(item["head_revision_id"])
        for item in workspace.list_branches(project)
    }


def test_branch_create_forks_expected_current_head(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "branch.db") as workspace:
        workspace.initialize("demo")
        program = workspace.create_program(
            "demo",
            "main",
            "main.weave",
            program_name="branch-create",
        )

        fork_revision = workspace.create_branch(
            "demo",
            "feature",
            from_branch="main",
            expected_revision_id=program["revision_id"],
        )

        assert fork_revision == program["revision_id"]
        assert _heads(workspace, "demo") == {
            "feature": program["revision_id"],
            "main": program["revision_id"],
        }


def test_stale_prepared_branch_create_inserts_no_branch(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "stale.db") as workspace:
        _, initial_revision = workspace.initialize("demo")
        program = workspace.create_program(
            "demo",
            "main",
            "main.weave",
            program_name="advanced",
            expected_revision_id=initial_revision,
        )

        with pytest.raises(ValidationError) as raised:
            workspace.create_branch(
                "demo",
                "stale",
                from_branch="main",
                expected_revision_id=initial_revision,
            )

        assert raised.value.code == "STALE_BRANCH_HEAD"
        assert _heads(workspace, "demo") == {"main": program["revision_id"]}


def test_unprepared_branch_create_rejects_mid_call_source_advance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "race.db"
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
        original_transaction = workspace.db.transaction
        competitor_revision: dict[str, str] = {}

        @contextmanager
        def racing_transaction() -> Iterator[object]:
            result = competitor.create_form(
                "demo",
                "main",
                "main.weave",
                program["node_id"],
                "competitor",
            )
            competitor_revision["revision_id"] = str(result["revision_id"])
            with original_transaction() as connection:
                yield connection

        monkeypatch.setattr(workspace.db, "transaction", racing_transaction)

        with pytest.raises(ValidationError) as raised:
            workspace.create_branch("demo", "lost", from_branch="main")

        assert raised.value.code == "STALE_BRANCH_HEAD"
        assert _heads(workspace, "demo") == {
            "main": competitor_revision["revision_id"]
        }


def test_branch_create_at_revision_forks_exact_historical_state(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "historical.db") as workspace:
        _, initial_revision = workspace.initialize("demo")
        program = workspace.create_program(
            "demo",
            "main",
            "main.weave",
            program_name="historical",
            expected_revision_id=initial_revision,
        )
        advanced = workspace.create_form(
            "demo",
            "main",
            "main.weave",
            program["node_id"],
            "advanced",
            expected_revision_id=program["revision_id"],
        )

        fork_revision = workspace.create_branch_at_revision(
            "demo",
            "historical",
            program["revision_id"],
        )

        assert fork_revision == program["revision_id"]
        assert _heads(workspace, "demo") == {
            "historical": program["revision_id"],
            "main": advanced["revision_id"],
        }
        assert workspace.find_nodes(
            "demo",
            "historical",
            "main.weave",
            head="advanced",
        ) == []
        assert len(
            workspace.find_nodes(
                "demo",
                "main",
                "main.weave",
                head="advanced",
            )
        ) == 1


def test_branch_create_at_revision_requires_project_ownership(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "ownership.db") as workspace:
        _, demo_revision = workspace.initialize("demo")
        _, other_revision = workspace.initialize("other")

        with pytest.raises(NotFoundError, match="does not belong"):
            workspace.create_branch_at_revision("demo", "foreign", other_revision)

        assert _heads(workspace, "demo") == {"main": demo_revision}


@pytest.mark.parametrize("revision_id", ["", 7, True])
def test_branch_create_at_revision_validates_revision_id(
    tmp_path: Path,
    revision_id: object,
) -> None:
    with SExpressionWorkspace(tmp_path / "invalid.db") as workspace:
        workspace.initialize("demo")

        with pytest.raises(ValidationError) as raised:
            workspace.create_branch_at_revision(
                "demo",
                "invalid",
                revision_id,  # type: ignore[arg-type]
            )

        assert raised.value.code == "INVALID_REVISION_ID"
        assert set(_heads(workspace, "demo")) == {"main"}


def test_branch_creation_returns_structured_duplicate_error(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "duplicate.db") as workspace:
        _, initial_revision = workspace.initialize("demo")
        assert workspace.create_branch("demo", "feature") == initial_revision

        with pytest.raises(ValidationError) as current:
            workspace.create_branch("demo", "feature")
        with pytest.raises(ValidationError) as historical:
            workspace.create_branch_at_revision(
                "demo",
                "feature",
                initial_revision,
            )

        assert current.value.code == "DUPLICATE_BRANCH"
        assert historical.value.code == "DUPLICATE_BRANCH"
        assert _heads(workspace, "demo") == {
            "feature": initial_revision,
            "main": initial_revision,
        }
