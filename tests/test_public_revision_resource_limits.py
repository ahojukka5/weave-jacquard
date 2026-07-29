from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any

import pytest

import weave_frontend.branch_activity as branch_activity_module
import weave_frontend.merge_preflight as merge_preflight_module
from weave_frontend.branch_activity import BranchActivityService
from weave_frontend.errors import ValidationError
from weave_frontend.merge_impact import MergeTargetImpactService
from weave_frontend.merge_preflight import MergePreflightService
from weave_frontend.project_merge_impact_queue import ProjectMergeImpactQueueService
from weave_frontend.project_merge_queue import ProjectMergeQueueService
from weave_frontend.resume_snapshot import ResumeSnapshotService
from weave_frontend.revision_diff import RevisionNodeDiffService
from weave_frontend.revision_inspection import RevisionNodeInspectionService
from weave_frontend.revision_limits import (
    MAX_BRANCH_ACTIVITY_REVISIONS,
    MAX_MERGE_TARGET_IMPACT_PAGE_SIZE,
    MAX_NODE_FIND_RESULTS,
    MAX_NODE_INSPECT_DEPTH,
    MAX_PREFLIGHT_IMPACT_TARGETS,
    MAX_PROJECT_MERGE_IMPACT_QUEUE_PAGE,
    MAX_PROJECT_MERGE_QUEUE_PAGE,
    MAX_RESUME_DOCUMENTS,
    MAX_REVISION_DIFF_PAGE_SIZE,
    REVISION_RESOURCE_LIMITS,
)
from weave_frontend.revision_reads import RevisionReadService
from weave_frontend.sexpr import make_atom, make_form


class _ReadWorkspace:
    def __init__(self) -> None:
        root = make_form("program")
        root["children"].append(make_atom("symbol", "first"))
        root["children"].append(make_atom("symbol", "second"))
        self.root = root
        self.db = SimpleNamespace(connection=None)

    def branch_head(self, project: str, branch: str = "main") -> str:
        return "r1"

    def _state_at_revision(self, revision_id: str) -> dict[str, dict[str, Any]]:
        return {"main.weave": self.root}


class _Grammar:
    @staticmethod
    def hint_for_node(node: dict[str, Any]) -> dict[str, Any]:
        return {"kind": node["kind"]}


class _InspectionWorkspace(_ReadWorkspace):
    grammar = _Grammar()

    def __init__(self) -> None:
        super().__init__()
        self.observed_depth: int | None = None

    def _truncate(self, node: dict[str, Any], depth: int) -> dict[str, Any]:
        self.observed_depth = depth
        return node


def test_node_find_reports_complete_count_and_presentation_truncation() -> None:
    service = RevisionReadService(_ReadWorkspace())

    result = service.find("demo", "main", "main.weave", limit=2)

    assert result["returned_count"] == 2
    assert result["matched_count"] == 2
    assert result["total_match_count"] == 4
    assert result["truncated"] is True
    assert result["has_more"] is True
    assert result["limits"] == {"maximum_results": MAX_NODE_FIND_RESULTS}


@pytest.mark.parametrize("value", [True, False, 0, -1, 1.5, "2"])
def test_node_find_rejects_invalid_limits(value: object) -> None:
    service = RevisionReadService(_ReadWorkspace())

    with pytest.raises(ValidationError) as captured:
        service.find("demo", "main", "main.weave", limit=value)  # type: ignore[arg-type]

    assert captured.value.code == "INVALID_NODE_FIND_LIMIT"


def test_node_find_accepts_the_configured_maximum() -> None:
    service = RevisionReadService(_ReadWorkspace())

    result = service.find(
        "demo",
        "main",
        "main.weave",
        limit=MAX_NODE_FIND_RESULTS,
    )

    assert result["truncated"] is False
    assert result["returned_count"] == result["total_match_count"]


def test_node_inspection_accepts_exact_depth_and_exposes_ceiling() -> None:
    workspace = _InspectionWorkspace()
    service = RevisionNodeInspectionService(workspace)

    result = service.inspect(
        "demo",
        "main",
        "main.weave",
        workspace.root["id"],
        depth=MAX_NODE_INSPECT_DEPTH,
    )

    assert workspace.observed_depth == MAX_NODE_INSPECT_DEPTH
    assert result["depth"] == MAX_NODE_INSPECT_DEPTH
    assert result["limits"] == {"maximum_depth": MAX_NODE_INSPECT_DEPTH}


@pytest.mark.parametrize("value", [True, False, -1, 1.5, "3"])
def test_node_inspection_rejects_invalid_depth(value: object) -> None:
    workspace = _InspectionWorkspace()
    service = RevisionNodeInspectionService(workspace)

    with pytest.raises(ValidationError) as captured:
        service.inspect(
            "demo",
            "main",
            "main.weave",
            workspace.root["id"],
            depth=value,  # type: ignore[arg-type]
        )

    assert captured.value.code == "INVALID_NODE_INSPECT_DEPTH"


def test_public_page_validators_accept_exact_and_reject_plus_one() -> None:
    RevisionNodeDiffService._validate_limit(MAX_REVISION_DIFF_PAGE_SIZE)
    MergeTargetImpactService._validate_limit(MAX_MERGE_TARGET_IMPACT_PAGE_SIZE)
    ProjectMergeQueueService._validate_limit(
        "limit",
        MAX_PROJECT_MERGE_QUEUE_PAGE,
        MAX_PROJECT_MERGE_QUEUE_PAGE,
    )
    ProjectMergeImpactQueueService._validate_limit(
        "limit",
        MAX_PROJECT_MERGE_IMPACT_QUEUE_PAGE,
        MAX_PROJECT_MERGE_IMPACT_QUEUE_PAGE,
    )
    ResumeSnapshotService._validate_limit(
        "document_limit",
        MAX_RESUME_DOCUMENTS,
        MAX_RESUME_DOCUMENTS,
    )

    checks = (
        (
            RevisionNodeDiffService._validate_limit,
            MAX_REVISION_DIFF_PAGE_SIZE + 1,
            "INVALID_REVISION_DIFF_LIMIT",
        ),
        (
            MergeTargetImpactService._validate_limit,
            MAX_MERGE_TARGET_IMPACT_PAGE_SIZE + 1,
            "INVALID_MERGE_TARGET_IMPACT_LIMIT",
        ),
    )
    for validator, value, code in checks:
        with pytest.raises(ValidationError) as captured:
            validator(value)
        assert captured.value.code == code

    with pytest.raises(ValidationError) as captured:
        ProjectMergeQueueService._validate_limit(
            "limit",
            MAX_PROJECT_MERGE_QUEUE_PAGE + 1,
            MAX_PROJECT_MERGE_QUEUE_PAGE,
        )
    assert captured.value.code == "INVALID_PROJECT_MERGE_QUEUE_LIMIT"

    with pytest.raises(ValidationError) as captured:
        ProjectMergeImpactQueueService._validate_limit(
            "limit",
            MAX_PROJECT_MERGE_IMPACT_QUEUE_PAGE + 1,
            MAX_PROJECT_MERGE_IMPACT_QUEUE_PAGE,
        )
    assert captured.value.code == "INVALID_PROJECT_MERGE_IMPACT_QUEUE_LIMIT"

    with pytest.raises(ValidationError) as captured:
        ResumeSnapshotService._validate_limit(
            "document_limit",
            MAX_RESUME_DOCUMENTS + 1,
            MAX_RESUME_DOCUMENTS,
        )
    assert captured.value.code == "INVALID_RESUME_SNAPSHOT_LIMIT"


class _ParentResult:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = row

    def fetchone(self) -> dict[str, Any] | None:
        return self.row


class _ParentConnection:
    def __init__(self, parents: dict[str, str | None]) -> None:
        self.parents = parents

    def execute(self, statement: str, parameters: tuple[str]) -> _ParentResult:
        assert statement.startswith("SELECT parent1_id")
        revision = parameters[0]
        if revision not in self.parents:
            return _ParentResult(None)
        return _ParentResult({"parent1_id": self.parents[revision]})


def test_first_parent_reachability_fails_closed_at_internal_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(branch_activity_module, "MAX_BRANCH_ACTIVITY_REVISIONS", 2)
    workspace = SimpleNamespace(
        db=SimpleNamespace(
            connection=_ParentConnection({"c": "b", "b": "a", "a": None})
        )
    )
    service = BranchActivityService(workspace)

    with pytest.raises(ValidationError) as captured:
        service._is_first_parent_reachable("c", "missing")

    assert captured.value.code == "BRANCH_HISTORY_SCAN_LIMIT_EXCEEDED"


class _HashDatabase:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def hash_value(self, value: dict[str, Any]) -> str:
        self.payloads.append(value)
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


class _ImpactService:
    def __init__(self) -> None:
        self.requested_limits: list[int] = []

    def page(self, *args: Any, limit: int, **kwargs: Any) -> dict[str, Any]:
        self.requested_limits.append(limit)
        return {
            "format": "weave-merge-target-impact-v1",
            "preview_id": "preview",
            "base_revision_id": "base",
            "target_head_revision_id": "target",
            "source_head_revision_id": "source",
            "merged_root_hash": "root",
            "changed_program_documents": [],
            "changed_target_documents": [],
            "candidate_covered_changed_documents": [],
            "uncovered_changed_documents": [],
            "total_target_count_before": 0,
            "total_target_count_after": 0,
            "total_affected_target_count": 0,
            "unaffected_target_count": 0,
            "returned_count": 0,
            "has_more": False,
            "truncated": False,
            "next_index": None,
            "limits": {"maximum_page_size": limit},
            "affected_targets": [],
        }


class _ValidationSets:
    def __init__(self, database: _HashDatabase) -> None:
        workspace = SimpleNamespace(db=database)
        self.validations = SimpleNamespace(workspace=workspace)

    def validate(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "validation_set_id": "validation-set",
            "ready_for_publication": True,
        }


def test_preflight_identity_binds_effective_impact_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _HashDatabase()
    impacts = _ImpactService()
    service = MergePreflightService(impacts, _ValidationSets(database))

    first = service.run("demo", "main", "feature")
    monkeypatch.setattr(merge_preflight_module, "MAX_PREFLIGHT_IMPACT_TARGETS", 1)
    second = service.run("demo", "main", "feature")

    assert impacts.requested_limits == [MAX_PREFLIGHT_IMPACT_TARGETS, 1]
    assert first["impact_limit"] == MAX_PREFLIGHT_IMPACT_TARGETS
    assert second["impact_limit"] == 1
    assert first["preflight_id"] != second["preflight_id"]
    assert database.payloads[0]["impact_limit"] == MAX_PREFLIGHT_IMPACT_TARGETS
    assert database.payloads[1]["impact_limit"] == 1


def test_central_limit_manifest_contains_public_revision_boundaries() -> None:
    assert REVISION_RESOURCE_LIMITS["node_find_results"] == MAX_NODE_FIND_RESULTS
    assert REVISION_RESOURCE_LIMITS["node_inspect_depth"] == MAX_NODE_INSPECT_DEPTH
    assert (
        REVISION_RESOURCE_LIMITS["revision_diff_page_size"]
        == MAX_REVISION_DIFF_PAGE_SIZE
    )
    assert (
        REVISION_RESOURCE_LIMITS["merge_target_impact_page_size"]
        == MAX_MERGE_TARGET_IMPACT_PAGE_SIZE
    )
    assert (
        REVISION_RESOURCE_LIMITS["branch_activity_revisions"]
        == MAX_BRANCH_ACTIVITY_REVISIONS
    )
