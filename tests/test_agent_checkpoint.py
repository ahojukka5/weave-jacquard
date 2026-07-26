from __future__ import annotations

from pathlib import Path

import pytest

from weave_frontend import SExpressionWorkspace, ValidationError
from weave_frontend.agent_checkpoint import (
    AGENT_CHECKPOINT_FORMAT,
    AGENT_CHECKPOINT_OPERATION,
    AGENT_CHECKPOINT_TITLE,
    MAX_CHECKPOINT_SUMMARY_CHARS,
    AgentCheckpointRegistry,
)


def _counts(workspace: SExpressionWorkspace) -> tuple[int, int, int, int]:
    connection = workspace.db.connection
    return tuple(
        int(connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])
        for table in ("revisions", "operations", "documents", "revision_documents")
    )


def _root_hash(workspace: SExpressionWorkspace, revision_id: str) -> str:
    row = workspace.db.connection.execute(
        "SELECT root_hash FROM revisions WHERE id = ?",
        (revision_id,),
    ).fetchone()
    return str(row["root_hash"])


def _checkpoint(
    registry: AgentCheckpointRegistry,
    revision_id: str,
    *,
    status: str = "in_progress",
    objective: str = "Finish the agent-native checkpoint protocol",
):
    return registry.create(
        "demo",
        "main",
        objective=objective,
        summary="The structural and concurrency foundations are complete.",
        status=status,
        completed=["Published race-safe writes", "Added resume snapshots"],
        next_steps=["Integrate checkpoints into resume snapshots"],
        open_questions=["Should checkpoints later support labels?"],
        validation=["syntax", "ruff", "pytest"],
        expected_revision_id=revision_id,
    )


def test_checkpoint_publication_preserves_program_state_and_audit(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "checkpoint.db") as workspace:
        workspace.initialize("demo")
        program = workspace.create_program(
            "demo",
            "main",
            "main.weave",
            program_name="checkpoint-demo",
        )
        registry = AgentCheckpointRegistry(workspace)

        result = _checkpoint(registry, str(program["revision_id"]))

        assert result["base_revision_id"] == program["revision_id"]
        assert result["revision_id"] == result["checkpoint_revision_id"]
        assert result["checkpoint_is_selected_revision"] is True
        assert result["checkpoint"]["format"] == AGENT_CHECKPOINT_FORMAT
        assert result["checkpoint"]["status"] == "in_progress"
        assert result["resume"] == {
            "tool": "branch_resume_snapshot",
            "arguments": {
                "project": "demo",
                "branch": "main",
                "revision_id": result["revision_id"],
            },
        }
        assert _root_hash(workspace, str(result["revision_id"])) == _root_hash(
            workspace,
            str(program["revision_id"]),
        )

        operation = workspace.db.connection.execute(
            """SELECT operation_kind, target, payload_json
               FROM operations WHERE revision_id = ?""",
            (result["revision_id"],),
        ).fetchone()
        assert operation["operation_kind"] == AGENT_CHECKPOINT_OPERATION
        assert operation["target"] == "main"
        linked = workspace.db.connection.execute(
            """SELECT d.title
               FROM revision_documents rd
               JOIN documents d ON d.id = rd.document_id
               WHERE rd.revision_id = ? AND d.id = ?""",
            (result["revision_id"], result["checkpoint_id"]),
        ).fetchone()
        assert linked["title"] == AGENT_CHECKPOINT_TITLE


def test_checkpoint_resolution_is_revision_pinned(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "history.db") as workspace:
        workspace.initialize("demo")
        program = workspace.create_program(
            "demo",
            "main",
            "main.weave",
            program_name="checkpoint-history",
        )
        registry = AgentCheckpointRegistry(workspace)
        first = _checkpoint(registry, str(program["revision_id"]))
        advanced = workspace.create_form(
            "demo",
            "main",
            "main.weave",
            str(program["node_id"]),
            "advanced",
            expected_revision_id=first["revision_id"],
        )
        second = _checkpoint(
            registry,
            str(advanced["revision_id"]),
            status="ready_for_review",
            objective="Review and merge checkpoint support",
        )

        historical = registry.get(
            "demo",
            "main",
            revision_id=str(first["revision_id"]),
        )
        between = registry.get(
            "demo",
            "main",
            revision_id=str(advanced["revision_id"]),
        )
        current = registry.get("demo", "main")

        assert historical["checkpoint_id"] == first["checkpoint_id"]
        assert historical["checkpoint_revision_id"] == first["revision_id"]
        assert historical["revision_is_branch_head"] is False
        assert between["checkpoint_id"] == first["checkpoint_id"]
        assert between["checkpoint_is_selected_revision"] is False
        assert between["resume"]["arguments"]["revision_id"] == first["revision_id"]
        assert current["checkpoint_id"] == second["checkpoint_id"]
        assert current["checkpoint"]["status"] == "ready_for_review"
        assert current["checkpoint_is_selected_revision"] is True


def test_checkpoint_get_reports_unconfigured_state(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "empty.db") as workspace:
        _, revision_id = workspace.initialize("demo")
        registry = AgentCheckpointRegistry(workspace)

        result = registry.get("demo", "main")

        assert result["configured"] is False
        assert result["revision_id"] == revision_id
        assert result["checkpoint"] is None
        assert result["checkpoint_id"] is None
        assert result["resume"] is None


def test_stale_checkpoint_publishes_no_revision_or_document(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "stale.db") as workspace:
        _, initial_revision = workspace.initialize("demo")
        program = workspace.create_program(
            "demo",
            "main",
            "main.weave",
            program_name="checkpoint-stale",
            expected_revision_id=initial_revision,
        )
        registry = AgentCheckpointRegistry(workspace)
        counts = _counts(workspace)

        with pytest.raises(ValidationError) as raised:
            _checkpoint(registry, initial_revision)

        assert raised.value.code == "STALE_BRANCH_HEAD"
        assert workspace.branch_head("demo", "main") == program["revision_id"]
        assert _counts(workspace) == counts
        assert registry.get("demo", "main")["configured"] is False


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"objective": ""}, "objective"),
        ({"summary": "x" * (MAX_CHECKPOINT_SUMMARY_CHARS + 1)}, "summary"),
        ({"status": "unknown"}, "status"),
        ({"completed": "not-a-list"}, "completed"),
        ({"next_steps": ["same", "same"]}, "duplicate"),
        ({"validation": [""]}, "validation item"),
    ],
)
def test_checkpoint_validates_structured_fields(
    tmp_path: Path,
    overrides: dict[str, object],
    message: str,
) -> None:
    with SExpressionWorkspace(tmp_path / f"invalid-{message}.db") as workspace:
        _, revision_id = workspace.initialize("demo")
        registry = AgentCheckpointRegistry(workspace)
        arguments: dict[str, object] = {
            "objective": "Objective",
            "summary": "Summary",
            "status": "in_progress",
            "completed": [],
            "next_steps": [],
            "open_questions": [],
            "validation": [],
        }
        arguments.update(overrides)

        with pytest.raises(ValidationError, match=message) as raised:
            registry.create(
                "demo",
                "main",
                expected_revision_id=revision_id,
                **arguments,  # type: ignore[arg-type]
            )

        assert raised.value.code == "INVALID_AGENT_CHECKPOINT"


def test_checkpoint_reader_rejects_tampered_document(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "tampered.db") as workspace:
        _, revision_id = workspace.initialize("demo")
        registry = AgentCheckpointRegistry(workspace)
        checkpoint = _checkpoint(registry, revision_id)
        workspace.db.connection.execute(
            "UPDATE documents SET body = ? WHERE id = ?",
            ('{"format":"weave-agent-checkpoint-v1","objective":"tampered"}', checkpoint["checkpoint_id"]),
        )
        workspace.db.connection.commit()

        with pytest.raises(ValidationError) as raised:
            registry.get("demo", "main")

        assert raised.value.code == "INVALID_AGENT_CHECKPOINT"
