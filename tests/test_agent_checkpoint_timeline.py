from __future__ import annotations

from pathlib import Path

import pytest

from weave_frontend import NotFoundError, SExpressionWorkspace, ValidationError
from weave_frontend.agent_checkpoint import AgentCheckpointRegistry
from weave_frontend.agent_checkpoint_timeline import (
    CHECKPOINT_COMPARISON_FORMAT,
    CHECKPOINT_TIMELINE_FORMAT,
    MAX_CHECKPOINT_PAGE,
    MAX_CHECKPOINT_REVISION_SCAN,
    MAX_TIMELINE_SUMMARY_PREVIEW_CHARS,
    AgentCheckpointTimelineService,
)


def _checkpoint(
    registry: AgentCheckpointRegistry,
    revision_id: str,
    *,
    objective: str,
    summary: str,
    status: str = "in_progress",
    completed: list[str] | None = None,
    next_steps: list[str] | None = None,
    open_questions: list[str] | None = None,
    validation: list[str] | None = None,
):
    return registry.create(
        "demo",
        "main",
        objective=objective,
        summary=summary,
        status=status,
        completed=completed,
        next_steps=next_steps,
        open_questions=open_questions,
        validation=validation,
        expected_revision_id=revision_id,
    )


def _timeline_state(
    workspace: SExpressionWorkspace,
) -> tuple[AgentCheckpointTimelineService, dict[str, object]]:
    workspace.initialize("demo")
    program = workspace.create_program(
        "demo",
        "main",
        "main.weave",
        program_name="checkpoint-timeline",
    )
    registry = AgentCheckpointRegistry(workspace)
    first = _checkpoint(
        registry,
        str(program["revision_id"]),
        objective="Build checkpoint supervision",
        summary="Initial handoff before implementation.",
        completed=["checkpoint protocol"],
        next_steps=["implement timeline", "add tests"],
        open_questions=["how should sparse history be bounded?"],
        validation=["syntax"],
    )
    edit_one = workspace.create_form(
        "demo",
        "main",
        "main.weave",
        str(program["node_id"]),
        "timeline",
        expected_revision_id=first["revision_id"],
    )
    edit_two = workspace.create_form(
        "demo",
        "main",
        "main.weave",
        str(program["node_id"]),
        "comparison",
        expected_revision_id=edit_one["revision_id"],
    )
    second = _checkpoint(
        registry,
        str(edit_two["revision_id"]),
        objective="Qualify checkpoint supervision",
        summary="Timeline and comparison services are implemented.",
        completed=["checkpoint protocol", "timeline implementation"],
        next_steps=["add tests", "write documentation"],
        open_questions=[],
        validation=["syntax", "ruff"],
    )
    edit_three = workspace.create_form(
        "demo",
        "main",
        "main.weave",
        str(program["node_id"]),
        "qualified",
        expected_revision_id=second["revision_id"],
    )
    third = _checkpoint(
        registry,
        str(edit_three["revision_id"]),
        objective="Merge checkpoint supervision",
        summary="x" * (MAX_TIMELINE_SUMMARY_PREVIEW_CHARS + 20),
        status="ready_for_review",
        completed=[
            "checkpoint protocol",
            "timeline implementation",
            "direct tests",
        ],
        next_steps=["merge pull request"],
        open_questions=[],
        validation=["syntax", "ruff", "pytest"],
    )
    return AgentCheckpointTimelineService(registry), {
        "program": program,
        "first": first,
        "edit_one": edit_one,
        "edit_two": edit_two,
        "second": second,
        "edit_three": edit_three,
        "third": third,
    }


def test_checkpoint_timeline_pages_first_parent_history_deterministically(
    tmp_path: Path,
) -> None:
    with SExpressionWorkspace(tmp_path / "timeline.db") as workspace:
        service, state = _timeline_state(workspace)

        first_page = service.page("demo", "main", limit=2, revision_scan_limit=20)
        repeated = service.page("demo", "main", limit=2, revision_scan_limit=20)

        assert first_page["format"] == CHECKPOINT_TIMELINE_FORMAT
        assert first_page["page_id"] == repeated["page_id"]
        assert first_page["start_revision_id"] == state["third"]["revision_id"]
        assert first_page["start_is_branch_head"] is True
        assert first_page["returned_checkpoint_count"] == 2
        assert first_page["checkpoint_limit_reached"] is True
        assert first_page["scan_limit_reached"] is False
        assert first_page["has_more"] is True
        assert first_page["next_revision_id"] == state["edit_one"]["revision_id"]
        assert [item["checkpoint_revision_id"] for item in first_page["checkpoints"]] == [
            state["third"]["revision_id"],
            state["second"]["revision_id"],
        ]
        latest = first_page["checkpoints"][0]
        assert len(latest["summary_preview"]) == MAX_TIMELINE_SUMMARY_PREVIEW_CHARS
        assert latest["summary_truncated"] is True
        assert latest["completed_count"] == 3
        assert latest["resume"] == {
            "tool": "branch_resume_snapshot",
            "arguments": {
                "project": "demo",
                "branch": "main",
                "revision_id": state["third"]["revision_id"],
            },
        }

        second_page = service.page(
            "demo",
            "main",
            start_revision_id=str(first_page["next_revision_id"]),
            limit=2,
            revision_scan_limit=20,
        )
        assert second_page["start_is_branch_head"] is False
        assert second_page["returned_checkpoint_count"] == 1
        assert second_page["checkpoints"][0]["checkpoint_revision_id"] == state[
            "first"
        ]["revision_id"]
        assert second_page["has_more"] is False
        assert second_page["next_revision_id"] is None


def test_sparse_checkpoint_scan_stops_at_explicit_revision_bound(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "sparse.db") as workspace:
        service, state = _timeline_state(workspace)

        page = service.page(
            "demo",
            "main",
            start_revision_id=str(state["edit_two"]["revision_id"]),
            limit=10,
            revision_scan_limit=1,
        )

        assert page["returned_checkpoint_count"] == 0
        assert page["scanned_revision_count"] == 1
        assert page["scan_limit_reached"] is True
        assert page["checkpoint_limit_reached"] is False
        assert page["next_revision_id"] == state["edit_one"]["revision_id"]
        assert page["has_more"] is True


def test_checkpoint_comparison_reports_structural_progress_deltas(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "compare.db") as workspace:
        service, state = _timeline_state(workspace)

        result = service.compare(
            "demo",
            str(state["first"]["revision_id"]),
            str(state["second"]["revision_id"]),
        )
        repeated = service.compare(
            "demo",
            str(state["first"]["revision_id"]),
            str(state["second"]["revision_id"]),
        )

        assert result["format"] == CHECKPOINT_COMPARISON_FORMAT
        assert result["comparison_id"] == repeated["comparison_id"]
        assert result["changed"] is True
        assert result["program_state_changed"] is True
        assert result["status"] == {
            "base": "in_progress",
            "target": "in_progress",
            "changed": False,
        }
        assert result["objective"]["changed"] is True
        assert result["summary"]["changed"] is True
        assert result["list_deltas"]["completed"]["added"] == [
            "timeline implementation"
        ]
        assert result["list_deltas"]["completed"]["removed"] == []
        assert result["list_deltas"]["next_steps"]["added"] == [
            "write documentation"
        ]
        assert result["list_deltas"]["next_steps"]["removed"] == [
            "implement timeline"
        ]
        assert result["list_deltas"]["open_questions"]["removed"] == [
            "how should sparse history be bounded?"
        ]
        assert result["list_deltas"]["validation"]["added"] == ["ruff"]
        assert "does not prove completion" in result["interpretation_note"]
        assert "does not imply" in result["ordering_note"]


def test_checkpoint_comparison_of_same_revision_is_unchanged(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "same.db") as workspace:
        service, state = _timeline_state(workspace)
        revision_id = str(state["second"]["revision_id"])

        result = service.compare("demo", revision_id, revision_id)

        assert result["changed"] is False
        assert result["program_state_changed"] is False
        assert result["status"]["changed"] is False
        assert result["objective"]["changed"] is False
        assert result["summary"]["changed"] is False
        assert all(
            delta["changed"] is False for delta in result["list_deltas"].values()
        )


def test_checkpoint_comparison_requires_exact_checkpoint_revisions(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "required.db") as workspace:
        service, state = _timeline_state(workspace)

        with pytest.raises(ValidationError) as raised:
            service.compare(
                "demo",
                str(state["edit_one"]["revision_id"]),
                str(state["second"]["revision_id"]),
            )

        assert raised.value.code == "CHECKPOINT_REVISION_REQUIRED"


@pytest.mark.parametrize(
    ("keyword", "value"),
    [
        ("limit", 0),
        ("limit", MAX_CHECKPOINT_PAGE + 1),
        ("revision_scan_limit", True),
        ("revision_scan_limit", MAX_CHECKPOINT_REVISION_SCAN + 1),
    ],
)
def test_checkpoint_timeline_validates_bounds(
    tmp_path: Path,
    keyword: str,
    value: object,
) -> None:
    with SExpressionWorkspace(tmp_path / f"invalid-{keyword}-{value}.db") as workspace:
        service, _ = _timeline_state(workspace)

        with pytest.raises(ValidationError) as raised:
            service.page("demo", "main", **{keyword: value})  # type: ignore[arg-type]

        assert raised.value.code == "INVALID_CHECKPOINT_TIMELINE_LIMIT"


def test_checkpoint_timeline_rejects_foreign_start_revision(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "foreign.db") as workspace:
        service, _ = _timeline_state(workspace)
        _, foreign_revision = workspace.initialize("other")

        with pytest.raises(NotFoundError, match="does not belong"):
            service.page(
                "demo",
                "main",
                start_revision_id=foreign_revision,
            )
