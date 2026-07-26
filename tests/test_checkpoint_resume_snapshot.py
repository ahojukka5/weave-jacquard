from __future__ import annotations

from pathlib import Path

from weave_frontend import SExpressionWorkspace
from weave_frontend.agent_checkpoint import AgentCheckpointRegistry
from weave_frontend.checkpoint_resume_snapshot import CheckpointResumeSnapshotService
from weave_frontend.concurrent_build_targets import BuildTargetRegistry
from weave_frontend.concurrent_merge_policy import MergePolicyRegistry


def _service(
    workspace: SExpressionWorkspace,
) -> tuple[CheckpointResumeSnapshotService, AgentCheckpointRegistry]:
    checkpoints = AgentCheckpointRegistry(workspace)
    return (
        CheckpointResumeSnapshotService(
            workspace,
            BuildTargetRegistry(workspace),
            MergePolicyRegistry(workspace),
            checkpoints,
        ),
        checkpoints,
    )


def _create_checkpoint(
    checkpoints: AgentCheckpointRegistry,
    revision_id: str,
    *,
    objective: str,
    status: str = "in_progress",
):
    return checkpoints.create(
        "demo",
        "main",
        objective=objective,
        summary=f"Summary for {objective}",
        status=status,
        completed=["one completed item"],
        next_steps=["one next step"],
        validation=["pytest"],
        expected_revision_id=revision_id,
    )


def test_resume_snapshot_reports_unconfigured_checkpoint(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "none.db") as workspace:
        workspace.initialize("demo")
        service, _ = _service(workspace)

        snapshot = service.snapshot("demo", "main")

        assert snapshot["agent_checkpoint"]["configured"] is False
        assert snapshot["agent_checkpoint"]["revision_id"] == snapshot["revision_id"]
        assert snapshot["agent_checkpoint"]["resume"] is None


def test_resume_snapshot_identity_includes_checkpoint(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "identity.db") as workspace:
        workspace.initialize("demo")
        program = workspace.create_program(
            "demo",
            "main",
            "main.weave",
            program_name="checkpoint-snapshot",
        )
        service, checkpoints = _service(workspace)
        before = service.snapshot("demo", "main")
        checkpoint = _create_checkpoint(
            checkpoints,
            str(program["revision_id"]),
            objective="Prepare the handoff",
        )

        after = service.snapshot("demo", "main")
        repeated = service.snapshot("demo", "main")

        assert before["snapshot_id"] != after["snapshot_id"]
        assert after["snapshot_id"] == repeated["snapshot_id"]
        assert after["revision_id"] == checkpoint["revision_id"]
        assert after["agent_checkpoint"]["checkpoint_id"] == checkpoint["checkpoint_id"]
        assert after["agent_checkpoint"]["checkpoint_is_selected_revision"] is True
        assert after["agent_checkpoint"]["checkpoint"]["objective"] == (
            "Prepare the handoff"
        )


def test_later_snapshot_keeps_checkpoint_resume_pinned_to_checkpoint_revision(
    tmp_path: Path,
) -> None:
    with SExpressionWorkspace(tmp_path / "later.db") as workspace:
        workspace.initialize("demo")
        program = workspace.create_program(
            "demo",
            "main",
            "main.weave",
            program_name="checkpoint-later",
        )
        service, checkpoints = _service(workspace)
        first = _create_checkpoint(
            checkpoints,
            str(program["revision_id"]),
            objective="Checkpoint before later edits",
        )
        advanced = workspace.create_form(
            "demo",
            "main",
            "main.weave",
            str(program["node_id"]),
            "advanced",
            expected_revision_id=first["revision_id"],
        )

        current = service.snapshot("demo", "main")
        historical = service.snapshot(
            "demo",
            "main",
            revision_id=str(first["revision_id"]),
        )

        assert current["revision_id"] == advanced["revision_id"]
        assert current["agent_checkpoint"]["checkpoint_revision_id"] == first[
            "revision_id"
        ]
        assert current["agent_checkpoint"]["checkpoint_is_selected_revision"] is False
        assert current["agent_checkpoint"]["resume"]["arguments"]["revision_id"] == (
            first["revision_id"]
        )
        assert historical["agent_checkpoint"]["checkpoint_id"] == first[
            "checkpoint_id"
        ]
        assert historical["agent_checkpoint"]["checkpoint_is_selected_revision"] is True


def test_historical_snapshot_does_not_borrow_later_checkpoint(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "history.db") as workspace:
        workspace.initialize("demo")
        program = workspace.create_program(
            "demo",
            "main",
            "main.weave",
            program_name="checkpoint-history",
        )
        service, checkpoints = _service(workspace)
        first = _create_checkpoint(
            checkpoints,
            str(program["revision_id"]),
            objective="First handoff",
        )
        advanced = workspace.create_form(
            "demo",
            "main",
            "main.weave",
            str(program["node_id"]),
            "advanced",
            expected_revision_id=first["revision_id"],
        )
        second = _create_checkpoint(
            checkpoints,
            str(advanced["revision_id"]),
            objective="Second handoff",
            status="ready_for_review",
        )

        first_snapshot = service.snapshot(
            "demo",
            "main",
            revision_id=str(first["revision_id"]),
        )
        second_snapshot = service.snapshot("demo", "main")

        assert first_snapshot["agent_checkpoint"]["checkpoint_id"] == first[
            "checkpoint_id"
        ]
        assert first_snapshot["agent_checkpoint"]["checkpoint"]["objective"] == (
            "First handoff"
        )
        assert second_snapshot["agent_checkpoint"]["checkpoint_id"] == second[
            "checkpoint_id"
        ]
        assert second_snapshot["agent_checkpoint"]["checkpoint"]["status"] == (
            "ready_for_review"
        )
