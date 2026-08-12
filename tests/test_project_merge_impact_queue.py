from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from weave_frontend import SExpressionWorkspace, ValidationError
from weave_frontend.builds import BuildTargetRegistry
from weave_frontend.merges import (
    PROJECT_MERGE_IMPACT_QUEUE_FORMAT,
    MergePolicyRegistry,
    MergePreviewService,
    MergeTargetImpactService,
    ProjectMergeImpactQueueService,
    ProjectMergeQueueService,
)
from weave_frontend.resume import AgentCheckpointRegistry, ProjectAgentStatusService
from weave_frontend.revision_limits import (
    MAX_PROJECT_MERGE_IMPACT_QUEUE_DOCUMENTS,
    MAX_PROJECT_MERGE_IMPACT_QUEUE_PAGE,
)


def _program_with_atoms(
    workspace: SExpressionWorkspace,
    document: str,
    values: list[str],
) -> dict[str, Any]:
    created = workspace.create_program(
        "demo",
        "main",
        document,
        program_name=document,
    )
    revision_id = str(created["revision_id"])
    atoms: list[str] = []
    for value in values:
        added = workspace.add_atom(
            "demo",
            "main",
            document,
            str(created["node_id"]),
            "string",
            value,
            expected_revision_id=revision_id,
        )
        revision_id = str(added["revision_id"])
        atoms.append(str(added["node_id"]))
    return {
        "root_id": str(created["node_id"]),
        "atom_ids": atoms,
        "revision_id": revision_id,
    }


def _checkpoint(
    registry: AgentCheckpointRegistry,
    branch: str,
    revision_id: str,
    objective: str,
) -> dict[str, Any]:
    return registry.create(
        "demo",
        branch,
        objective=objective,
        summary=f"Checkpoint for {branch}",
        completed=["prepared impact candidate"],
        next_steps=["review target coverage"],
        validation=["syntax"],
        expected_revision_id=revision_id,
    )


def _impact_state(
    workspace: SExpressionWorkspace,
) -> tuple[ProjectMergeImpactQueueService, dict[str, Any]]:
    workspace.initialize("demo")
    main = _program_with_atoms(workspace, "main.weave", ["conflict", "covered"])
    lib = _program_with_atoms(workspace, "lib.weave", ["lib"])
    orphan = _program_with_atoms(workspace, "orphan.weave", ["orphan"])
    _program_with_atoms(workspace, "spare.weave", ["spare"])

    targets = BuildTargetRegistry(workspace)
    targets.set(
        "demo",
        "main",
        "application",
        "main.weave",
        additional_documents=["lib.weave"],
    )
    targets.set("demo", "main", "main-only", "main.weave")
    targets.set("demo", "main", "spare", "spare.weave")

    policies = MergePolicyRegistry(workspace)
    target_policy_revision = policies.set(
        "demo",
        "main",
        require_preflight=True,
        require_affected_validation=True,
        allow_uncovered_documents=False,
        max_affected_targets=3,
    )
    base_revision = str(target_policy_revision["revision_id"])
    for branch in ("conflict", "covered", "target-only", "uncovered"):
        workspace.create_branch_at_revision("demo", branch, base_revision)

    covered_policy = policies.set(
        "demo",
        "covered",
        require_preflight=False,
        require_affected_validation=False,
        allow_uncovered_documents=True,
        max_affected_targets=10,
    )
    covered_main = workspace.set_atom(
        "demo",
        "covered",
        "main.weave",
        main["atom_ids"][1],
        "covered-main",
        expected_revision_id=covered_policy["revision_id"],
    )
    covered_lib = workspace.set_atom(
        "demo",
        "covered",
        "lib.weave",
        lib["atom_ids"][0],
        "covered-lib",
        expected_revision_id=covered_main["revision_id"],
    )

    registry = AgentCheckpointRegistry(workspace)
    covered_checkpoint = _checkpoint(
        registry,
        "covered",
        str(covered_lib["revision_id"]),
        "Review covered program changes",
    )
    conflict_checkpoint = _checkpoint(
        registry,
        "conflict",
        base_revision,
        "Resolve stable atom conflict",
    )
    conflict_head = workspace.set_atom(
        "demo",
        "conflict",
        "main.weave",
        main["atom_ids"][0],
        "source-conflict",
        expected_revision_id=conflict_checkpoint["revision_id"],
    )
    uncovered_head = workspace.set_atom(
        "demo",
        "uncovered",
        "orphan.weave",
        orphan["atom_ids"][0],
        "source-orphan",
        expected_revision_id=base_revision,
    )
    target_only = targets.set(
        "demo",
        "target-only",
        "application",
        "main.weave",
        additional_documents=["lib.weave", "orphan.weave"],
    )
    target_head = workspace.set_atom(
        "demo",
        "main",
        "main.weave",
        main["atom_ids"][0],
        "target-conflict",
        expected_revision_id=base_revision,
    )
    workspace.create_branch_at_revision(
        "demo",
        "noop",
        str(target_head["revision_id"]),
    )

    previews = MergePreviewService(workspace)
    statuses = ProjectAgentStatusService(registry)
    queues = ProjectMergeQueueService(previews, statuses)
    impacts = MergeTargetImpactService(previews, targets)
    return ProjectMergeImpactQueueService(queues, impacts, policies), {
        "base_revision": base_revision,
        "main": main,
        "covered_policy": covered_policy,
        "covered_checkpoint": covered_checkpoint,
        "conflict_checkpoint": conflict_checkpoint,
        "conflict_head": conflict_head,
        "uncovered_head": uncovered_head,
        "target_only": target_only,
        "target_head": target_head,
    }


def test_project_merge_impact_queue_composes_exact_policy_and_coverage_evidence(
    tmp_path: Path,
) -> None:
    with SExpressionWorkspace(tmp_path / "impact-queue.db") as workspace:
        service, state = _impact_state(workspace)

        first = service.page(
            "demo",
            limit=3,
            checkpoint_scan_limit=20,
            conflict_limit=1,
            changed_document_limit=1,
            affected_target_limit=1,
            coverage_document_limit=1,
        )
        repeated = service.page(
            "demo",
            limit=3,
            checkpoint_scan_limit=20,
            conflict_limit=1,
            changed_document_limit=1,
            affected_target_limit=1,
            coverage_document_limit=1,
        )

        assert first["format"] == PROJECT_MERGE_IMPACT_QUEUE_FORMAT
        assert first["page_id"] == repeated["page_id"]
        assert first["catalog_id"] == repeated["catalog_id"]
        assert first["target_head_revision_id"] == state["target_head"]["revision_id"]
        assert first["source_catalog_count"] == 5
        assert first["returned_source_count"] == 3
        assert first["has_more"] is True
        assert first["next_after_source"] == "noop"
        assert [item["source_branch"] for item in first["sources"]] == [
            "conflict",
            "covered",
            "noop",
        ]
        target_policy = first["target_merge_policy"]
        assert target_policy["revision_id"] == state["target_head"]["revision_id"]
        assert target_policy["allow_uncovered_documents"] is False
        assert target_policy["require_preflight"] is True
        assert target_policy["max_affected_targets"] == 3
        assert "no compiler or build validation was run" in first["compiler_note"]
        assert "target revision policy is authoritative" in first["authority_note"]
        assert "do not prove compiler correctness" in first["readiness_note"]

        conflict = first["sources"][0]
        assert conflict["source_head_revision_id"] == state["conflict_head"][
            "revision_id"
        ]
        assert conflict["impact_classification"] == "conflicted"
        assert conflict["impact"] is None
        assert conflict["coverage_gate"] is None
        assert conflict["impact_call"] is None
        assert conflict["preflight"] is None
        assert conflict["source_checkpoint"]["checkpoint_state"] == "behind_head"
        assert conflict["source_checkpoint"]["revisions_since_checkpoint"] == 1
        assert conflict["merge_policy"]["source_policy_ignored"] is False

        covered = first["sources"][1]
        assert covered["source_head_revision_id"] == state["covered_checkpoint"][
            "revision_id"
        ]
        assert covered["impact_classification"] == "covered_program_changes"
        impact = covered["impact"]
        assert impact["changed_program_document_count"] == 2
        assert impact["changed_program_documents"] == ["lib.weave"]
        assert impact["changed_program_documents_truncated"] is True
        assert impact["covered_changed_document_count"] == 2
        assert impact["covered_changed_documents"] == ["lib.weave"]
        assert impact["covered_changed_documents_truncated"] is True
        assert impact["uncovered_changed_document_count"] == 0
        assert impact["total_affected_target_count"] == 2
        assert impact["returned_affected_target_count"] == 1
        assert impact["affected_targets_truncated"] is True
        assert impact["next_affected_target_index"] == 1
        assert impact["affected_targets"][0]["name"] == "application"
        assert covered["coverage_gate"] == {
            "uncovered_documents_present": False,
            "target_allows_uncovered_documents": False,
            "override_possible": False,
        }
        assert covered["source_checkpoint"]["checkpoint_state"] == "head"
        assert covered["merge_policy"]["source_policy_ignored"] is True
        assert covered["merge_policy"]["source"]["policy_hash"] == state[
            "covered_policy"
        ]["policy_hash"]
        assert covered["merge_policy"]["target"]["policy_hash"] == target_policy[
            "policy_hash"
        ]
        assert covered["impact_call"] == {
            "tool": "branch_merge_impact",
            "arguments": {
                "project": "demo",
                "target_branch": "main",
                "source_branch": "covered",
                "preview_id": covered["preview_id"],
                "start_index": 0,
                "limit": 1,
            },
        }
        assert covered["preflight"]["arguments"]["preview_id"] == covered[
            "preview_id"
        ]

        noop = first["sources"][2]
        assert noop["impact_classification"] == "no_changes"
        assert noop["impact"]["changed_program_document_count"] == 0
        assert noop["impact"]["changed_target_document_count"] == 0
        assert noop["impact"]["total_affected_target_count"] == 0
        assert noop["coverage_gate"]["uncovered_documents_present"] is False

        second = service.page(
            "demo",
            start_after_source=first["next_after_source"],
            catalog_id=first["catalog_id"],
            limit=3,
            checkpoint_scan_limit=20,
            conflict_limit=1,
            changed_document_limit=1,
            affected_target_limit=1,
            coverage_document_limit=1,
        )
        assert second["has_more"] is False
        assert [item["source_branch"] for item in second["sources"]] == [
            "target-only",
            "uncovered",
        ]

        target_only = second["sources"][0]
        assert target_only["source_head_revision_id"] == state["target_only"][
            "revision_id"
        ]
        assert target_only["impact_classification"] == (
            "target_definition_changes_only"
        )
        assert target_only["impact"]["changed_program_document_count"] == 0
        assert target_only["impact"]["changed_target_document_count"] == 1
        assert target_only["impact"]["changed_target_documents"] == [
            "@build-target/application"
        ]
        assert target_only["impact"]["total_affected_target_count"] == 1

        uncovered = second["sources"][1]
        assert uncovered["source_head_revision_id"] == state["uncovered_head"][
            "revision_id"
        ]
        assert uncovered["impact_classification"] == "uncovered_program_changes"
        assert uncovered["impact"]["uncovered_changed_document_count"] == 1
        assert uncovered["impact"]["uncovered_changed_documents"] == [
            "orphan.weave"
        ]
        assert uncovered["coverage_gate"] == {
            "uncovered_documents_present": True,
            "target_allows_uncovered_documents": False,
            "override_possible": False,
        }
        assert uncovered["merge_policy"]["source_policy_ignored"] is False


def test_conflicted_source_stops_before_impact_analysis(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "conflict-short-circuit.db") as workspace:
        service, _ = _impact_state(workspace)

        class _CountingImpacts:
            def __init__(self) -> None:
                self.calls = 0

            def page(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
                self.calls += 1
                raise AssertionError("conflicted source must not request impact")

        counting = _CountingImpacts()
        service.impacts = counting  # type: ignore[assignment]

        page = service.page("demo", limit=1, checkpoint_scan_limit=20)

        assert page["sources"][0]["source_branch"] == "conflict"
        assert page["sources"][0]["impact_classification"] == "conflicted"
        assert counting.calls == 0


def test_project_merge_impact_queue_rejects_stale_catalog(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "stale.db") as workspace:
        service, state = _impact_state(workspace)
        page = service.page("demo", limit=2, checkpoint_scan_limit=20)

        workspace.create_form(
            "demo",
            "covered",
            "main.weave",
            state["main"]["root_id"],
            "later",
            expected_revision_id=state["covered_checkpoint"]["revision_id"],
        )

        with pytest.raises(ValidationError) as raised:
            service.page(
                "demo",
                start_after_source=page["next_after_source"],
                catalog_id=page["catalog_id"],
                limit=2,
            )

        assert raised.value.code == "STALE_PROJECT_MERGE_QUEUE_CATALOG"


@pytest.mark.parametrize(
    ("keyword", "value"),
    [
        ("limit", 0),
        ("limit", MAX_PROJECT_MERGE_IMPACT_QUEUE_PAGE + 1),
        ("checkpoint_scan_limit", True),
        ("conflict_limit", 101),
        ("changed_document_limit", 201),
        ("affected_target_limit", 201),
        ("coverage_document_limit", MAX_PROJECT_MERGE_IMPACT_QUEUE_DOCUMENTS + 1),
    ],
)
def test_project_merge_impact_queue_validates_bounds(
    tmp_path: Path,
    keyword: str,
    value: object,
) -> None:
    with SExpressionWorkspace(tmp_path / f"invalid-{keyword}.db") as workspace:
        service, _ = _impact_state(workspace)

        with pytest.raises(ValidationError) as raised:
            service.page("demo", **{keyword: value})  # type: ignore[arg-type]

        assert raised.value.code == "INVALID_PROJECT_MERGE_IMPACT_QUEUE_LIMIT"
