from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from weave_frontend.errors import ValidationError
from weave_frontend.merge_preflight import MergePreflightService


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
    def __init__(self) -> None:
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
        return {
            "format": "weave-merge-target-impact-v1",
            "preview_id": "preview",
            "base_revision_id": "base",
            "target_head_revision_id": "target-head",
            "source_head_revision_id": "source-head",
            "merged_root_hash": "a" * 64,
            "changed_program_documents": ["main.weave"],
            "changed_target_documents": [],
            "candidate_covered_changed_documents": ["main.weave"],
            "uncovered_changed_documents": [],
            "total_target_count_before": 2,
            "total_target_count_after": 2,
            "total_affected_target_count": 2,
            "unaffected_target_count": 0,
            "returned_count": 2,
            "has_more": False,
            "next_index": None,
            "affected_targets": [
                {"name": "application", "after": {"name": "application"}},
                {"name": "mirror", "after": {"name": "mirror"}},
            ],
        }


class _ValidationSetService:
    validations = _Validations()

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def validate(
        self,
        project: str,
        target_branch: str,
        source_branch: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "project": project,
                "target_branch": target_branch,
                "source_branch": source_branch,
                **kwargs,
            }
        )
        return {
            "format": "weave-merge-validation-set-v1",
            "validation_set_id": self.validations.workspace.db.hash_value(kwargs),
            "preview_id": "preview",
            "ready_for_publication": True,
            "coverage_passed": True,
            "passed_targets": ["application", "mirror"],
            "failed_targets": [],
            "unavailable_targets": [],
            "target_validations": [],
        }


class _PolicyRegistry:
    def __init__(
        self,
        *,
        target_hash: str = "target-policy",
        source_hash: str = "source-policy",
        allow_uncovered: bool = False,
        maximum: int = 2,
    ) -> None:
        self.target_hash = target_hash
        self.source_hash = source_hash
        self.allow_uncovered = allow_uncovered
        self.maximum = maximum
        self.calls: list[tuple[str, str, str]] = []

    def compare(
        self,
        project: str,
        target_branch: str,
        source_branch: str,
    ) -> dict[str, Any]:
        self.calls.append((project, target_branch, source_branch))
        return {
            "target": {
                "configured": True,
                "policy_hash": self.target_hash,
                "require_preflight": True,
                "require_affected_validation": True,
                "allow_uncovered_documents": self.allow_uncovered,
                "max_affected_targets": self.maximum,
            },
            "source": {
                "configured": True,
                "policy_hash": self.source_hash,
                "require_preflight": False,
                "require_affected_validation": False,
                "allow_uncovered_documents": True,
                "max_affected_targets": 64,
            },
            "source_policy_ignored": self.target_hash != self.source_hash,
        }


def _service(policies: _PolicyRegistry):
    impacts = _ImpactService()
    validations = _ValidationSetService()
    return MergePreflightService(impacts, validations, policies), impacts, validations


def test_preflight_uses_target_policy_and_ignores_weaker_source_policy() -> None:
    service, _, validations = _service(_PolicyRegistry(maximum=2))

    result = service.run("demo", "protected", "incoming")

    assert result["target_merge_policy"]["policy_hash"] == "target-policy"
    assert result["source_merge_policy"]["policy_hash"] == "source-policy"
    assert result["source_policy_ignored"] is True
    assert result["validation_set"]["ready_for_publication"] is True
    assert validations.calls == [
        {
            "project": "demo",
            "target_branch": "protected",
            "source_branch": "incoming",
            "preview_id": "preview",
            "allow_uncovered_documents": False,
            "max_target_validations": 2,
        }
    ]
    assert result["publication_arguments"]["preflight_id"] == result["preflight_id"]
    assert result["publication_arguments"]["validate_affected_targets"] is True


def test_policy_hashes_are_bound_into_preflight_identity() -> None:
    first, _, _ = _service(_PolicyRegistry(target_hash="strict-a", source_hash="weak"))
    second, _, _ = _service(_PolicyRegistry(target_hash="strict-b", source_hash="weak"))
    third, _, _ = _service(_PolicyRegistry(target_hash="strict-a", source_hash="different-source"))

    first_result = first.run("demo", "protected", "incoming")
    second_result = second.run("demo", "protected", "incoming")
    third_result = third.run("demo", "protected", "incoming")

    assert first_result["preflight_id"] != second_result["preflight_id"]
    assert first_result["preflight_id"] != third_result["preflight_id"]


def test_forbidden_uncovered_override_fails_before_impact_or_validation() -> None:
    service, impacts, validations = _service(_PolicyRegistry(allow_uncovered=False))

    with pytest.raises(ValidationError) as raised:
        service.run(
            "demo",
            "protected",
            "incoming",
            allow_uncovered_documents=True,
        )

    assert raised.value.code == "MERGE_POLICY_VIOLATION"
    assert impacts.calls == []
    assert validations.calls == []


def test_allowed_uncovered_override_is_policy_bound() -> None:
    service, _, validations = _service(_PolicyRegistry(allow_uncovered=True, maximum=5))

    result = service.run(
        "demo",
        "protected",
        "incoming",
        allow_uncovered_documents=True,
    )

    assert result["allow_uncovered_documents"] is True
    assert result["publication_arguments"]["allow_uncovered_documents"] is True
    assert validations.calls[0]["allow_uncovered_documents"] is True
    assert validations.calls[0]["max_target_validations"] == 5
