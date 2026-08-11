from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from weave_frontend.errors import ValidationError
from weave_frontend.merges import MERGE_PREFLIGHT_FORMAT, MergePreflightService
from weave_frontend.revision_limits import MAX_PREFLIGHT_IMPACT_TARGETS


class _Database:
    @staticmethod
    def hash_value(value: Any) -> str:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


class _Workspace:
    db = _Database()


class _Validations:
    workspace = _Workspace()


class _ImpactService:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def page(
        self,
        project: str,
        target_branch: str,
        source_branch: str,
        *,
        preview_id: str | None,
        start_index: int,
        limit: int,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "project": project,
                "target_branch": target_branch,
                "source_branch": source_branch,
                "preview_id": preview_id,
                "start_index": start_index,
                "limit": limit,
            }
        )
        return dict(self.result)


class _ValidationSetService:
    validations = _Validations()

    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def validate(
        self,
        project: str,
        target_branch: str,
        source_branch: str,
        *,
        preview_id: str | None,
        allow_uncovered_documents: bool,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "project": project,
                "target_branch": target_branch,
                "source_branch": source_branch,
                "preview_id": preview_id,
                "allow_uncovered_documents": allow_uncovered_documents,
            }
        )
        return dict(self.result)


def _impact(*, truncated: bool = False) -> dict[str, Any]:
    return {
        "format": "weave-merge-target-impact-v1",
        "project": "demo",
        "target_branch": "main",
        "source_branch": "agent/feature",
        "preview_id": "preview-123",
        "base_revision_id": "base-revision",
        "target_head_revision_id": "target-revision",
        "source_head_revision_id": "source-revision",
        "merged_root_hash": "a" * 64,
        "changed_program_documents": ["main.weave"],
        "changed_target_documents": [],
        "candidate_covered_changed_documents": ["main.weave"],
        "uncovered_changed_documents": [],
        "total_target_count_before": 3,
        "total_target_count_after": 3,
        "total_affected_target_count": 2,
        "unaffected_target_count": 1,
        "start_index": 0,
        "limit": MAX_PREFLIGHT_IMPACT_TARGETS,
        "returned_count": 2,
        "has_more": truncated,
        "next_index": 200 if truncated else None,
        "affected_targets": [
            {
                "name": "application",
                "status": "unchanged",
                "affected_reasons": ["source_document_changed"],
                "changed_source_documents": ["main.weave"],
                "before": {"name": "application", "document": "main.weave"},
                "after": {"name": "application", "document": "main.weave"},
            },
            {
                "name": "mirror",
                "status": "unchanged",
                "affected_reasons": ["source_document_changed"],
                "changed_source_documents": ["main.weave"],
                "before": {"name": "mirror", "document": "main.weave"},
                "after": {"name": "mirror", "document": "main.weave"},
            },
        ],
    }


def _validation_set(*, ready: bool = True) -> dict[str, Any]:
    return {
        "format": "weave-merge-validation-set-v1",
        "validation_set_id": "validation-set-456",
        "preview_id": "preview-123",
        "merged_root_hash": "a" * 64,
        "coverage_passed": ready,
        "ready_for_publication": ready,
        "uncovered_changed_documents": [] if ready else ["orphan.weave"],
        "affected_surviving_targets": ["application", "mirror"],
        "passed_targets": ["application", "mirror"] if ready else [],
        "failed_targets": [],
        "unavailable_targets": [],
        "target_validations": [],
    }


def test_preflight_is_deterministic_and_returns_repeatable_publication_arguments() -> None:
    impacts = _ImpactService(_impact())
    validation_sets = _ValidationSetService(_validation_set())
    service = MergePreflightService(impacts, validation_sets)

    first = service.run("demo", "main", "agent/feature")
    second = service.run("demo", "main", "agent/feature")

    assert first == second
    assert first["format"] == MERGE_PREFLIGHT_FORMAT
    assert len(first["preflight_id"]) == 64
    assert first["ready_for_publication"] is True
    assert first["impact_targets_truncated"] is False
    assert first["impact"]["returned_count"] == 2
    assert first["validation_set"]["validation_set_id"] == "validation-set-456"
    assert first["publication_tool"] == "branch_merge"
    assert first["publication_arguments"] == {
        "project": "demo",
        "target_branch": "main",
        "source_branch": "agent/feature",
        "preview_id": "preview-123",
        "validate_affected_targets": True,
        "allow_uncovered_documents": False,
    }
    assert impacts.calls[0]["limit"] == MAX_PREFLIGHT_IMPACT_TARGETS
    assert impacts.calls[0]["start_index"] == 0
    assert validation_sets.calls[0]["preview_id"] == "preview-123"


def test_preflight_preserves_non_ready_coverage_result() -> None:
    impact = _impact()
    impact["uncovered_changed_documents"] = ["orphan.weave"]
    impacts = _ImpactService(impact)
    validation_sets = _ValidationSetService(_validation_set(ready=False))

    result = MergePreflightService(impacts, validation_sets).run(
        "demo", "main", "agent/feature"
    )

    assert result["ready_for_publication"] is False
    assert result["impact"]["uncovered_changed_documents"] == ["orphan.weave"]
    assert result["validation_set"]["coverage_passed"] is False
    assert result["publication_arguments"]["allow_uncovered_documents"] is False


def test_preflight_identity_binds_uncovered_document_policy() -> None:
    impacts = _ImpactService(_impact())
    validation_sets = _ValidationSetService(_validation_set())
    service = MergePreflightService(impacts, validation_sets)

    strict = service.run("demo", "main", "agent/feature")
    allowed = service.run(
        "demo",
        "main",
        "agent/feature",
        allow_uncovered_documents=True,
    )

    assert strict["preflight_id"] != allowed["preflight_id"]
    assert allowed["allow_uncovered_documents"] is True
    assert allowed["publication_arguments"]["allow_uncovered_documents"] is True
    assert validation_sets.calls[-1]["allow_uncovered_documents"] is True


def test_preflight_reports_bounded_impact_truncation() -> None:
    impacts = _ImpactService(_impact(truncated=True))
    validation_sets = _ValidationSetService(_validation_set())

    result = MergePreflightService(impacts, validation_sets).run(
        "demo", "main", "agent/feature"
    )

    assert result["impact_targets_truncated"] is True
    assert result["impact"]["has_more"] is True
    assert result["impact"]["next_index"] == 200


def test_preflight_propagates_stale_preview_errors() -> None:
    class _StaleImpact:
        def page(self, *_: Any, **__: Any) -> dict[str, Any]:
            raise ValidationError(
                "STALE_MERGE_PREVIEW",
                "one or both branch heads changed after review",
            )

    service = MergePreflightService(
        _StaleImpact(),  # type: ignore[arg-type]
        _ValidationSetService(_validation_set()),
    )

    with pytest.raises(ValidationError) as raised:
        service.run(
            "demo",
            "main",
            "agent/feature",
            preview_id="old-preview",
        )
    assert raised.value.code == "STALE_MERGE_PREVIEW"
