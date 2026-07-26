from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from weave_frontend import SExpressionWorkspace, ValidationError
from weave_frontend.agent_checkpoint import AgentCheckpointRegistry
from weave_frontend.merge_preview import MergePreviewService
from weave_frontend.project_agent_status import ProjectAgentStatusService
from weave_frontend.project_merge_queue import ProjectMergeQueueService
from weave_frontend.selected_merge_train_preview import (
    MAX_SELECTED_MERGE_TRAIN_SOURCES,
    SELECTED_MERGE_TRAIN_FORMAT,
    SelectedMergeTrainPreviewService,
)


def _train_state(
    workspace: SExpressionWorkspace,
) -> tuple[SelectedMergeTrainPreviewService, dict[str, Any]]:
    workspace.initialize("demo")
    program = workspace.create_program(
        "demo",
        "main",
        "main.weave",
        program_name="selected-merge-train",
    )
    revision_id = str(program["revision_id"])
    atoms: list[str] = []
    for value in (0, 0, 0):
        added = workspace.add_atom(
            "demo",
            "main",
            "main.weave",
            str(program["node_id"]),
            "integer",
            value,
            expected_revision_id=revision_id,
        )
        revision_id = str(added["revision_id"])
        atoms.append(str(added["node_id"]))
    base_revision = revision_id
    target = workspace.set_atom(
        "demo",
        "main",
        "main.weave",
        atoms[1],
        1,
        expected_revision_id=base_revision,
    )
    target_head = str(target["revision_id"])

    for branch in (
        "alpha",
        "beta",
        "bridge",
        "same-one",
        "same-two",
        "unselected",
    ):
        workspace.create_branch_at_revision("demo", branch, target_head)
    workspace.create_branch_at_revision("demo", "legacy", base_revision)

    alpha = workspace.set_atom(
        "demo",
        "alpha",
        "main.weave",
        atoms[0],
        10,
        expected_revision_id=target_head,
    )
    beta = workspace.set_atom(
        "demo",
        "beta",
        "main.weave",
        atoms[0],
        20,
        expected_revision_id=target_head,
    )
    same_one = workspace.set_atom(
        "demo",
        "same-one",
        "main.weave",
        atoms[2],
        30,
        expected_revision_id=target_head,
    )
    same_two = workspace.set_atom(
        "demo",
        "same-two",
        "main.weave",
        atoms[2],
        30,
        expected_revision_id=target_head,
    )
    bridge = workspace.set_atom(
        "demo",
        "bridge",
        "main.weave",
        atoms[1],
        2,
        expected_revision_id=target_head,
    )
    legacy = workspace.set_atom(
        "demo",
        "legacy",
        "main.weave",
        atoms[1],
        2,
        expected_revision_id=base_revision,
    )

    previews = MergePreviewService(workspace)
    statuses = ProjectAgentStatusService(AgentCheckpointRegistry(workspace))
    queues = ProjectMergeQueueService(previews, statuses)
    catalog_id = str(queues.page("demo", limit=10)["catalog_id"])
    return SelectedMergeTrainPreviewService(queues), {
        "program": program,
        "atoms": atoms,
        "base_revision": base_revision,
        "target_head": target_head,
        "alpha": alpha,
        "beta": beta,
        "same_one": same_one,
        "same_two": same_two,
        "bridge": bridge,
        "legacy": legacy,
        "catalog_id": catalog_id,
    }


def test_train_detects_order_introduced_conflict_and_stops(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "introduced.db") as workspace:
        service, state = _train_state(workspace)

        result = service.preview(
            "demo",
            "main",
            ["alpha", "beta", "same-one"],
            state["catalog_id"],
            conflict_limit=1,
            changed_document_limit=1,
        )
        repeated = service.preview(
            "demo",
            "main",
            ["alpha", "beta", "same-one"],
            state["catalog_id"],
            conflict_limit=1,
            changed_document_limit=1,
        )

        assert result["format"] == SELECTED_MERGE_TRAIN_FORMAT
        assert result["train_id"] == repeated["train_id"]
        assert result["target_head_revision_id"] == state["target_head"]
        assert result["selected_source_count"] == 3
        assert result["simulated_source_count"] == 2
        assert result["applied_source_count"] == 1
        assert result["train_complete"] is False
        assert result["conflict_step_index"] == 1
        assert result["remaining_sources_not_simulated"] == ["same-one"]
        assert result["final_virtual_target_root_hash"] == result["steps"][0][
            "virtual_target_root_after"
        ]

        alpha = result["steps"][0]
        assert alpha["source_head_revision_id"] == state["alpha"]["revision_id"]
        assert alpha["original_preview_mergeable"] is True
        assert alpha["train_step_mergeable"] is True
        assert alpha["relation_to_original_preview"] == "consistent_clean"
        assert alpha["changed_documents"] == ["main.weave"]
        assert alpha["publication_requires_refresh_after_prior_step"] is False

        beta = result["steps"][1]
        assert beta["source_head_revision_id"] == state["beta"]["revision_id"]
        assert beta["original_preview_mergeable"] is True
        assert beta["train_step_mergeable"] is False
        assert beta["relation_to_original_preview"] == "order_introduced_conflict"
        assert beta["conflict_count"] >= 1
        assert len(beta["conflicts"]) == 1
        assert state["atoms"][0] in beta["conflicts"][0]
        assert beta["publication_requires_refresh_after_prior_step"] is True

        assert result["first_publication_candidate"] == {
            "tool": "branch_merge_preflight",
            "arguments": {
                "project": "demo",
                "target_branch": "main",
                "source_branch": "alpha",
                "preview_id": alpha["original_preview_id"],
            },
        }
        assert "structural and in-memory only" in result["simulation_note"]
        assert "fresh catalog and preflight" in result["refresh_note"]
        assert "can change train conflicts" in result["ordering_note"]


def test_train_marks_identical_later_source_as_redundant(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "redundant.db") as workspace:
        service, state = _train_state(workspace)

        result = service.preview(
            "demo",
            "main",
            ["same-one", "same-two"],
            state["catalog_id"],
        )

        assert result["train_complete"] is True
        assert result["applied_source_count"] == 2
        assert result["conflict_step_index"] is None
        assert result["remaining_sources_not_simulated"] == []
        first, second = result["steps"]
        assert first["train_step_mergeable"] is True
        assert first["no_changes"] is False
        assert second["original_preview_mergeable"] is True
        assert second["train_step_mergeable"] is True
        assert second["relation_to_original_preview"] == "consistent_clean"
        assert second["no_changes"] is True
        assert second["changed_document_count"] == 0
        assert second["virtual_target_root_before"] == second[
            "virtual_target_root_after"
        ]
        assert second["publication_requires_refresh_after_prior_step"] is True


def test_train_can_remove_original_conflict_after_bridge_source(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "removed.db") as workspace:
        service, state = _train_state(workspace)
        original_legacy = service.previews.preview("demo", "main", "legacy")
        assert original_legacy["mergeable"] is False

        result = service.preview(
            "demo",
            "main",
            ["bridge", "legacy"],
            state["catalog_id"],
        )

        assert result["train_complete"] is True
        bridge, legacy = result["steps"]
        assert bridge["original_preview_mergeable"] is True
        assert bridge["train_step_mergeable"] is True
        assert legacy["source_head_revision_id"] == state["legacy"]["revision_id"]
        assert legacy["original_preview_mergeable"] is False
        assert legacy["train_step_mergeable"] is True
        assert legacy["relation_to_original_preview"] == "order_removed_conflict"
        assert legacy["no_changes"] is True
        assert legacy["virtual_target_root_before"] == legacy[
            "virtual_target_root_after"
        ]


def test_train_rejects_stale_catalog_before_simulation(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "stale.db") as workspace:
        service, state = _train_state(workspace)
        workspace.create_program(
            "demo",
            "unselected",
            "later.weave",
            program_name="later",
            expected_revision_id=state["target_head"],
        )

        with pytest.raises(ValidationError) as raised:
            service.preview(
                "demo",
                "main",
                ["alpha"],
                state["catalog_id"],
            )

        assert raised.value.code == "STALE_SELECTED_MERGE_TRAIN_CATALOG"


def test_train_rechecks_whole_catalog_after_simulation(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "race.db") as workspace:
        service, state = _train_state(workspace)
        original_step = service._step
        mutated = False

        def mutating_step(*args: Any, **kwargs: Any) -> dict[str, Any]:
            nonlocal mutated
            result = original_step(*args, **kwargs)
            if not mutated:
                workspace.create_program(
                    "demo",
                    "unselected",
                    "race.weave",
                    program_name="race",
                    expected_revision_id=workspace.branch_head("demo", "unselected"),
                )
                mutated = True
            return result

        service._step = mutating_step  # type: ignore[method-assign]

        with pytest.raises(ValidationError) as raised:
            service.preview(
                "demo",
                "main",
                ["same-one", "same-two"],
                state["catalog_id"],
            )

        assert raised.value.code == "STALE_SELECTED_MERGE_TRAIN_CATALOG"


@pytest.mark.parametrize(
    ("sources", "code"),
    [
        ([], "INVALID_SELECTED_MERGE_TRAIN_SOURCES"),
        (["alpha", "alpha"], "INVALID_SELECTED_MERGE_TRAIN_SOURCES"),
        (
            ["alpha"] * (MAX_SELECTED_MERGE_TRAIN_SOURCES + 1),
            "INVALID_SELECTED_MERGE_TRAIN_SOURCES",
        ),
        (["missing"], "INVALID_SELECTED_MERGE_TRAIN_SOURCE"),
    ],
)
def test_train_validates_source_selection(
    tmp_path: Path,
    sources: list[str],
    code: str,
) -> None:
    with SExpressionWorkspace(tmp_path / f"invalid-{code}.db") as workspace:
        service, state = _train_state(workspace)

        with pytest.raises(ValidationError) as raised:
            service.preview("demo", "main", sources, state["catalog_id"])

        assert raised.value.code == code


@pytest.mark.parametrize(
    ("keyword", "value"),
    [
        ("conflict_limit", 0),
        ("conflict_limit", 101),
        ("changed_document_limit", True),
        ("changed_document_limit", 201),
    ],
)
def test_train_validates_bounds(
    tmp_path: Path,
    keyword: str,
    value: object,
) -> None:
    with SExpressionWorkspace(tmp_path / f"invalid-{keyword}.db") as workspace:
        service, state = _train_state(workspace)

        with pytest.raises(ValidationError) as raised:
            service.preview(
                "demo",
                "main",
                ["alpha"],
                state["catalog_id"],
                **{keyword: value},  # type: ignore[arg-type]
            )

        assert raised.value.code == "INVALID_SELECTED_MERGE_TRAIN_LIMIT"
