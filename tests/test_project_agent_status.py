from __future__ import annotations

from pathlib import Path

import pytest

from weave_frontend import SExpressionWorkspace, ValidationError
from weave_frontend.agent_checkpoint import AgentCheckpointRegistry
from weave_frontend.project_agent_status import (
    MAX_AGENT_STATUS_BRANCH_CATALOG,
    MAX_AGENT_STATUS_CHECKPOINT_SCAN,
    MAX_AGENT_STATUS_PAGE,
    PROJECT_AGENT_STATUS_FORMAT,
    ProjectAgentStatusService,
)


def _checkpoint(
    registry: AgentCheckpointRegistry,
    branch: str,
    revision_id: str,
    *,
    objective: str,
    status: str = "in_progress",
):
    return registry.create(
        "demo",
        branch,
        objective=objective,
        summary=f"Checkpoint for {branch}",
        status=status,
        completed=["one item"],
        next_steps=["one next step"],
        validation=["pytest"],
        expected_revision_id=revision_id,
    )


def _status_state(
    workspace: SExpressionWorkspace,
) -> tuple[ProjectAgentStatusService, dict[str, object]]:
    workspace.initialize("demo")
    program = workspace.create_program(
        "demo",
        "main",
        "main.weave",
        program_name="project-agent-status",
    )
    registry = AgentCheckpointRegistry(workspace)

    main_checkpoint = _checkpoint(
        registry,
        "main",
        str(program["revision_id"]),
        objective="Advance main after checkpoint",
    )
    main_head = workspace.create_form(
        "demo",
        "main",
        "main.weave",
        str(program["node_id"]),
        "main-advanced",
        expected_revision_id=main_checkpoint["revision_id"],
    )

    workspace.create_branch_at_revision(
        "demo",
        "feature",
        str(main_checkpoint["revision_id"]),
    )
    feature_checkpoint = _checkpoint(
        registry,
        "feature",
        str(main_checkpoint["revision_id"]),
        objective="Review feature checkpoint",
        status="ready_for_review",
    )

    workspace.create_branch_at_revision(
        "demo",
        "uncheckpointed",
        str(program["revision_id"]),
    )
    uncheckpointed_head = workspace.create_form(
        "demo",
        "uncheckpointed",
        "main.weave",
        str(program["node_id"]),
        "uncheckpointed-edit",
        expected_revision_id=program["revision_id"],
    )

    workspace.create_branch_at_revision(
        "demo",
        "sparse",
        str(program["revision_id"]),
    )
    sparse_one = workspace.create_form(
        "demo",
        "sparse",
        "main.weave",
        str(program["node_id"]),
        "sparse-one",
        expected_revision_id=program["revision_id"],
    )
    sparse_two = workspace.create_form(
        "demo",
        "sparse",
        "main.weave",
        str(program["node_id"]),
        "sparse-two",
        expected_revision_id=sparse_one["revision_id"],
    )
    sparse_head = workspace.create_form(
        "demo",
        "sparse",
        "main.weave",
        str(program["node_id"]),
        "sparse-three",
        expected_revision_id=sparse_two["revision_id"],
    )

    return ProjectAgentStatusService(registry), {
        "program": program,
        "main_checkpoint": main_checkpoint,
        "main_head": main_head,
        "feature_checkpoint": feature_checkpoint,
        "uncheckpointed_head": uncheckpointed_head,
        "sparse_head": sparse_head,
    }


def test_project_agent_status_pages_stable_catalog_and_branch_evidence(
    tmp_path: Path,
) -> None:
    with SExpressionWorkspace(tmp_path / "status.db") as workspace:
        service, state = _status_state(workspace)

        first = service.page(
            "demo",
            limit=2,
            checkpoint_scan_limit=2,
        )
        repeated = service.page(
            "demo",
            limit=2,
            checkpoint_scan_limit=2,
        )

        assert first["format"] == PROJECT_AGENT_STATUS_FORMAT
        assert first["page_id"] == repeated["page_id"]
        assert first["catalog_id"] == repeated["catalog_id"]
        assert first["branch_catalog_count"] == 4
        assert first["returned_branch_count"] == 2
        assert first["has_more"] is True
        assert first["next_after_branch"] == "main"
        assert [item["branch"] for item in first["branches"]] == ["feature", "main"]

        feature = first["branches"][0]
        assert feature["head_revision_id"] == state["feature_checkpoint"]["revision_id"]
        assert feature["checkpoint_state"] == "head"
        assert feature["checkpoint_is_head"] is True
        assert feature["revisions_since_checkpoint"] == 0
        assert feature["revisions_scanned"] == 1
        assert feature["program_state_changed_since_checkpoint"] is False
        assert feature["checkpoint"]["status"] == "ready_for_review"
        assert feature["checkpoint"]["resume"] == {
            "tool": "branch_resume_snapshot",
            "arguments": {
                "project": "demo",
                "branch": "feature",
                "revision_id": state["feature_checkpoint"]["revision_id"],
            },
        }

        main = first["branches"][1]
        assert main["head_revision_id"] == state["main_head"]["revision_id"]
        assert main["checkpoint_state"] == "behind_head"
        assert main["checkpoint_is_head"] is False
        assert main["revisions_since_checkpoint"] == 1
        assert main["revisions_scanned"] == 2
        assert main["program_state_changed_since_checkpoint"] is True
        assert (
            main["checkpoint"]["checkpoint_revision_id"] == state["main_checkpoint"]["revision_id"]
        )
        assert main["resume_head"]["arguments"] == {
            "project": "demo",
            "branch": "main",
            "revision_id": state["main_head"]["revision_id"],
        }

        second = service.page(
            "demo",
            start_after_branch=first["next_after_branch"],
            catalog_id=first["catalog_id"],
            limit=2,
            checkpoint_scan_limit=2,
        )
        assert second["has_more"] is False
        assert second["next_after_branch"] is None
        assert [item["branch"] for item in second["branches"]] == [
            "sparse",
            "uncheckpointed",
        ]

        sparse = second["branches"][0]
        assert sparse["head_revision_id"] == state["sparse_head"]["revision_id"]
        assert sparse["checkpoint_state"] == "not_found_within_scan"
        assert sparse["checkpoint"] is None
        assert sparse["checkpoint_scan_limit_reached"] is True
        assert sparse["complete_first_parent_history_scanned"] is False
        assert sparse["checkpoint_lag_lower_bound"] == 2
        assert sparse["revisions_since_checkpoint"] is None
        assert sparse["program_state_changed_since_checkpoint"] is None

        uncheckpointed = second["branches"][1]
        assert uncheckpointed["head_revision_id"] == state["uncheckpointed_head"]["revision_id"]
        assert uncheckpointed["checkpoint_state"] == "not_found_within_scan"
        assert uncheckpointed["checkpoint_scan_limit_reached"] is True

        complete = service.page(
            "demo",
            start_after_branch="sparse",
            catalog_id=first["catalog_id"],
            limit=1,
            checkpoint_scan_limit=10,
        )["branches"][0]
        assert complete["branch"] == "uncheckpointed"
        assert complete["checkpoint_state"] == "none_in_first_parent_history"
        assert complete["complete_first_parent_history_scanned"] is True
        assert complete["checkpoint_scan_limit_reached"] is False
        assert complete["checkpoint_lag_lower_bound"] is None


def test_agent_status_catalog_rejects_branch_head_change(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "stale.db") as workspace:
        service, state = _status_state(workspace)
        page = service.page("demo", limit=2, checkpoint_scan_limit=2)
        workspace.create_form(
            "demo",
            "main",
            "main.weave",
            str(state["program"]["node_id"]),
            "later-main",
            expected_revision_id=state["main_head"]["revision_id"],
        )

        with pytest.raises(ValidationError) as raised:
            service.page(
                "demo",
                start_after_branch=page["next_after_branch"],
                catalog_id=page["catalog_id"],
                limit=2,
                checkpoint_scan_limit=2,
            )

        assert raised.value.code == "STALE_AGENT_STATUS_CATALOG"


def test_agent_status_rejects_cursor_outside_current_catalog(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "cursor.db") as workspace:
        service, _ = _status_state(workspace)

        with pytest.raises(ValidationError) as raised:
            service.page("demo", start_after_branch="missing")

        assert raised.value.code == "INVALID_AGENT_STATUS_CURSOR"


@pytest.mark.parametrize(
    ("keyword", "value"),
    [
        ("limit", 0),
        ("limit", MAX_AGENT_STATUS_PAGE + 1),
        ("checkpoint_scan_limit", True),
        ("checkpoint_scan_limit", MAX_AGENT_STATUS_CHECKPOINT_SCAN + 1),
        ("catalog_id", ""),
        ("start_after_branch", 42),
    ],
)
def test_agent_status_validates_bounds_and_ids(
    tmp_path: Path,
    keyword: str,
    value: object,
) -> None:
    with SExpressionWorkspace(tmp_path / f"invalid-{keyword}.db") as workspace:
        service, _ = _status_state(workspace)

        with pytest.raises(ValidationError):
            service.page("demo", **{keyword: value})  # type: ignore[arg-type]


def test_agent_status_rejects_unbounded_branch_fanout(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "fanout.db") as workspace:
        project_id, revision_id = workspace.initialize("demo")
        workspace.db.connection.executemany(
            "INSERT INTO branches(project_id, name, head_revision_id) VALUES (?, ?, ?)",
            [
                (project_id, f"branch-{index:04d}", revision_id)
                for index in range(MAX_AGENT_STATUS_BRANCH_CATALOG)
            ],
        )
        workspace.db.connection.commit()
        service = ProjectAgentStatusService(AgentCheckpointRegistry(workspace))

        with pytest.raises(ValidationError) as raised:
            service.page("demo")

        assert raised.value.code == "AGENT_STATUS_BRANCH_FANOUT_EXCEEDED"
