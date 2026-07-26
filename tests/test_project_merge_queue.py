from __future__ import annotations

from pathlib import Path

import pytest

from weave_frontend import SExpressionWorkspace, ValidationError
from weave_frontend.agent_checkpoint import AgentCheckpointRegistry
from weave_frontend.merge_preview import MergePreviewService
from weave_frontend.project_agent_status import (
    MAX_AGENT_STATUS_BRANCH_CATALOG,
    ProjectAgentStatusService,
)
from weave_frontend.project_merge_queue import (
    MAX_PROJECT_MERGE_QUEUE_CONFLICTS,
    MAX_PROJECT_MERGE_QUEUE_DOCUMENTS,
    MAX_PROJECT_MERGE_QUEUE_PAGE,
    PROJECT_MERGE_QUEUE_FORMAT,
    ProjectMergeQueueService,
)


def _checkpoint(
    registry: AgentCheckpointRegistry,
    branch: str,
    revision_id: str,
    *,
    objective: str,
) -> dict[str, object]:
    return registry.create(
        "demo",
        branch,
        objective=objective,
        summary=f"Checkpoint for {branch}",
        status="in_progress",
        completed=["prepared merge candidate"],
        next_steps=["run merge preflight"],
        validation=["syntax"],
        expected_revision_id=revision_id,
    )


def _queue_state(
    workspace: SExpressionWorkspace,
) -> tuple[ProjectMergeQueueService, dict[str, object]]:
    workspace.initialize("demo")
    program = workspace.create_program(
        "demo",
        "main",
        "main.weave",
        program_name="project-merge-queue",
    )
    atom = workspace.add_atom(
        "demo",
        "main",
        "main.weave",
        str(program["node_id"]),
        "string",
        "base",
        expected_revision_id=program["revision_id"],
    )
    base_revision = str(atom["revision_id"])

    workspace.create_branch_at_revision("demo", "clean", base_revision)
    workspace.create_branch_at_revision("demo", "conflict", base_revision)

    clean_one = workspace.create_program(
        "demo",
        "clean",
        "clean-one.weave",
        program_name="clean-one",
        expected_revision_id=base_revision,
    )
    clean_two = workspace.create_program(
        "demo",
        "clean",
        "clean-two.weave",
        program_name="clean-two",
        expected_revision_id=clean_one["revision_id"],
    )

    registry = AgentCheckpointRegistry(workspace)
    clean_checkpoint = _checkpoint(
        registry,
        "clean",
        str(clean_two["revision_id"]),
        objective="Review clean source",
    )
    conflict_checkpoint = _checkpoint(
        registry,
        "conflict",
        base_revision,
        objective="Resolve conflicting atom",
    )
    conflict_head = workspace.set_atom(
        "demo",
        "conflict",
        "main.weave",
        str(atom["node_id"]),
        "source-value",
        expected_revision_id=conflict_checkpoint["revision_id"],
    )
    target_head = workspace.set_atom(
        "demo",
        "main",
        "main.weave",
        str(atom["node_id"]),
        "target-value",
        expected_revision_id=base_revision,
    )
    workspace.create_branch_at_revision(
        "demo",
        "noop",
        str(target_head["revision_id"]),
    )

    previews = MergePreviewService(workspace)
    statuses = ProjectAgentStatusService(registry)
    return ProjectMergeQueueService(previews, statuses), {
        "program": program,
        "atom": atom,
        "base_revision": base_revision,
        "clean_checkpoint": clean_checkpoint,
        "conflict_checkpoint": conflict_checkpoint,
        "conflict_head": conflict_head,
        "target_head": target_head,
    }


def test_project_merge_queue_pages_exact_catalog_and_compact_previews(
    tmp_path: Path,
) -> None:
    with SExpressionWorkspace(tmp_path / "queue.db") as workspace:
        service, state = _queue_state(workspace)

        first = service.page(
            "demo",
            limit=2,
            checkpoint_scan_limit=20,
            conflict_limit=1,
            changed_document_limit=1,
        )
        repeated = service.page(
            "demo",
            limit=2,
            checkpoint_scan_limit=20,
            conflict_limit=1,
            changed_document_limit=1,
        )

        assert first["format"] == PROJECT_MERGE_QUEUE_FORMAT
        assert first["page_id"] == repeated["page_id"]
        assert first["catalog_id"] == repeated["catalog_id"]
        assert first["target_branch"] == "main"
        assert first["target_head_revision_id"] == state["target_head"]["revision_id"]
        assert first["source_catalog_count"] == 3
        assert first["returned_source_count"] == 2
        assert first["has_more"] is True
        assert first["next_after_source"] == "conflict"
        assert [item["source_branch"] for item in first["sources"]] == [
            "clean",
            "conflict",
        ]
        assert "structural preview success only" in first["readiness_note"]
        assert "does not represent merge priority" in first["priority_note"]

        clean = first["sources"][0]
        assert clean["source_head_revision_id"] == state["clean_checkpoint"][
            "revision_id"
        ]
        assert clean["classification"] == "clean_changes"
        assert clean["mergeable"] is True
        assert clean["conflict_count"] == 0
        assert clean["conflicts"] == []
        assert clean["changed_document_count"] == 2
        assert clean["changed_documents"] == ["clean-one.weave"]
        assert clean["changed_documents_truncated"] is True
        assert clean["merged_root_hash"] is not None
        assert clean["source_checkpoint"]["checkpoint_state"] == "head"
        assert clean["source_checkpoint"]["checkpoint_is_head"] is True
        assert clean["source_checkpoint"]["revisions_since_checkpoint"] == 0
        assert clean["full_preview"] == {
            "tool": "branch_merge_preview",
            "arguments": {
                "project": "demo",
                "target_branch": "main",
                "source_branch": "clean",
            },
        }
        assert clean["preflight"] == {
            "tool": "branch_merge_preflight",
            "arguments": {
                "project": "demo",
                "target_branch": "main",
                "source_branch": "clean",
                "preview_id": clean["preview_id"],
            },
        }

        conflict = first["sources"][1]
        assert conflict["source_head_revision_id"] == state["conflict_head"][
            "revision_id"
        ]
        assert conflict["classification"] == "conflicted"
        assert conflict["mergeable"] is False
        assert conflict["conflict_count"] >= 1
        assert len(conflict["conflicts"]) == 1
        assert state["atom"]["node_id"] in conflict["conflicts"][0]
        assert conflict["conflicts_truncated"] is (
            conflict["conflict_count"] > 1
        )
        assert conflict["changed_document_count"] == 0
        assert conflict["merged_root_hash"] is None
        assert conflict["preflight"] is None
        assert conflict["source_checkpoint"]["checkpoint_state"] == "behind_head"
        assert conflict["source_checkpoint"]["checkpoint_is_head"] is False
        assert conflict["source_checkpoint"]["revisions_since_checkpoint"] == 1
        assert conflict["source_checkpoint"][
            "program_state_changed_since_checkpoint"
        ] is True

        second = service.page(
            "demo",
            start_after_source=first["next_after_source"],
            catalog_id=first["catalog_id"],
            limit=2,
            checkpoint_scan_limit=20,
            conflict_limit=1,
            changed_document_limit=1,
        )
        assert second["has_more"] is False
        assert second["next_after_source"] is None
        assert [item["source_branch"] for item in second["sources"]] == ["noop"]
        noop = second["sources"][0]
        assert noop["classification"] == "clean_no_changes"
        assert noop["mergeable"] is True
        assert noop["changed_document_count"] == 0
        assert noop["merged_root_hash"] == noop["target_root_hash"]
        assert noop["source_checkpoint"]["checkpoint_state"] == (
            "none_in_first_parent_history"
        )
        assert noop["preflight"]["arguments"]["preview_id"] == noop["preview_id"]


def test_project_merge_queue_rejects_stale_catalog_after_source_or_target_change(
    tmp_path: Path,
) -> None:
    with SExpressionWorkspace(tmp_path / "stale.db") as workspace:
        service, state = _queue_state(workspace)
        page = service.page("demo", limit=1, checkpoint_scan_limit=20)

        workspace.create_program(
            "demo",
            "clean",
            "later.weave",
            program_name="later",
            expected_revision_id=state["clean_checkpoint"]["revision_id"],
        )
        with pytest.raises(ValidationError) as source_error:
            service.page(
                "demo",
                start_after_source=page["next_after_source"],
                catalog_id=page["catalog_id"],
                limit=1,
            )
        assert source_error.value.code == "STALE_PROJECT_MERGE_QUEUE_CATALOG"

        refreshed = service.page("demo", limit=1)
        workspace.create_form(
            "demo",
            "main",
            "main.weave",
            str(state["program"]["node_id"]),
            "target-later",
            expected_revision_id=state["target_head"]["revision_id"],
        )
        with pytest.raises(ValidationError) as target_error:
            service.page(
                "demo",
                start_after_source=refreshed["next_after_source"],
                catalog_id=refreshed["catalog_id"],
                limit=1,
            )
        assert target_error.value.code == "STALE_PROJECT_MERGE_QUEUE_CATALOG"


@pytest.mark.parametrize(
    ("keyword", "value"),
    [
        ("limit", 0),
        ("limit", MAX_PROJECT_MERGE_QUEUE_PAGE + 1),
        ("checkpoint_scan_limit", True),
        ("checkpoint_scan_limit", 501),
        ("conflict_limit", MAX_PROJECT_MERGE_QUEUE_CONFLICTS + 1),
        ("changed_document_limit", MAX_PROJECT_MERGE_QUEUE_DOCUMENTS + 1),
    ],
)
def test_project_merge_queue_validates_bounds(
    tmp_path: Path,
    keyword: str,
    value: object,
) -> None:
    with SExpressionWorkspace(tmp_path / f"invalid-{keyword}.db") as workspace:
        service, _ = _queue_state(workspace)

        with pytest.raises(ValidationError) as raised:
            service.page("demo", **{keyword: value})  # type: ignore[arg-type]

        assert raised.value.code == "INVALID_PROJECT_MERGE_QUEUE_LIMIT"


def test_project_merge_queue_validates_target_cursor_and_catalog(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "invalid.db") as workspace:
        service, _ = _queue_state(workspace)

        with pytest.raises(ValidationError) as target_error:
            service.page("demo", target_branch="missing")
        assert target_error.value.code == "INVALID_MERGE_QUEUE_TARGET"

        with pytest.raises(ValidationError) as cursor_error:
            service.page("demo", start_after_source="missing")
        assert cursor_error.value.code == "INVALID_MERGE_QUEUE_CURSOR"

        with pytest.raises(ValidationError) as catalog_error:
            service.page("demo", catalog_id="wrong")
        assert catalog_error.value.code == "STALE_PROJECT_MERGE_QUEUE_CATALOG"


def test_project_merge_queue_rejects_unbounded_branch_fanout(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "fanout.db") as workspace:
        _, revision_id = workspace.initialize("demo")
        project_id = workspace.project_id("demo")
        rows = [
            (f"branch-{index:04d}", project_id, revision_id)
            for index in range(MAX_AGENT_STATUS_BRANCH_CATALOG + 1)
        ]
        workspace.db.connection.executemany(
            "INSERT INTO branches(name, project_id, head_revision_id) VALUES (?, ?, ?)",
            rows,
        )
        workspace.db.connection.commit()
        registry = AgentCheckpointRegistry(workspace)
        service = ProjectMergeQueueService(
            MergePreviewService(workspace),
            ProjectAgentStatusService(registry),
        )

        with pytest.raises(ValidationError) as raised:
            service.page("demo")

        assert raised.value.code == "MERGE_QUEUE_BRANCH_FANOUT_EXCEEDED"
