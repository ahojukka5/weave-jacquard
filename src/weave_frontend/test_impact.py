"""Non-executing structural behavioral-test impact plans between exact revisions."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .errors import ValidationError
from .project_metadata import BUILD_TARGET_PREFIX, TEST_TARGET_PREFIX

TEST_IMPACT_PLAN_FORMAT = "weave-test-impact-plan-v1"
DEFAULT_TEST_IMPACT_PAGE_SIZE = 50
MAX_TEST_IMPACT_PAGE_SIZE = 100
DEFAULT_TEST_IMPACT_EVIDENCE_LIMIT = 100
MAX_TEST_IMPACT_EVIDENCE_LIMIT = 500
_REASON_ORDER = (
    "test_definition_changed",
    "build_target_changed",
    "source_changed",
)


class TestImpactPlanService:
    """Explain structurally affected behavioral tests without executing them."""

    def __init__(self, workspace: Any, build_targets: Any, tests: Any) -> None:
        self.workspace = workspace
        self.build_targets = build_targets
        self.tests = tests

    def page(
        self,
        project: str,
        base_revision_id: str,
        *,
        branch: str = "main",
        target_revision_id: str | None = None,
        start_after_name: str | None = None,
        limit: int = DEFAULT_TEST_IMPACT_PAGE_SIZE,
        evidence_limit: int = DEFAULT_TEST_IMPACT_EVIDENCE_LIMIT,
    ) -> dict[str, Any]:
        """Return one deterministic lexical page from an exact structural impact plan."""

        self._validate_limit(
            "limit",
            limit,
            maximum=MAX_TEST_IMPACT_PAGE_SIZE,
        )
        self._validate_limit(
            "evidence_limit",
            evidence_limit,
            maximum=MAX_TEST_IMPACT_EVIDENCE_LIMIT,
        )
        if start_after_name is not None:
            self.tests._validate_name(start_after_name)

        target_revision = target_revision_id or self.workspace.branch_head(project, branch)
        self.tests._require_project_revision(project, base_revision_id)
        self.tests._require_project_revision(project, target_revision)
        base_state = self.workspace._state_at_revision(base_revision_id)
        target_state = self.workspace._state_at_revision(target_revision)
        changed_documents = self._changed_documents(base_state, target_state)
        changed_program_documents = sorted(
            document
            for document in changed_documents
            if not document.startswith((BUILD_TARGET_PREFIX, TEST_TARGET_PREFIX))
        )
        changed_build_targets = sorted(
            document[len(BUILD_TARGET_PREFIX) :]
            for document in changed_documents
            if document.startswith(BUILD_TARGET_PREFIX)
        )
        changed_test_targets = sorted(
            document[len(TEST_TARGET_PREFIX) :]
            for document in changed_documents
            if document.startswith(TEST_TARGET_PREFIX)
        )

        base_targets = {
            item["name"]: item
            for item in self.build_targets.list(
                project,
                branch=branch,
                revision_id=base_revision_id,
            )
        }
        target_targets = {
            item["name"]: item
            for item in self.build_targets.list(
                project,
                branch=branch,
                revision_id=target_revision,
            )
        }
        base_tests = {
            item["name"]: item
            for item in self.tests.list(
                project,
                branch=branch,
                revision_id=base_revision_id,
            )
        }
        target_tests = {
            item["name"]: item
            for item in self.tests.list(
                project,
                branch=branch,
                revision_id=target_revision,
            )
        }

        impacted_tests: list[dict[str, Any]] = []
        covered_changed_program_documents: set[str] = set()
        referenced_target_names: set[str] = set()
        for name in sorted(target_tests):
            definition = target_tests[name]
            target_name = str(definition["build_target"])
            target = target_targets[target_name]
            referenced_target_names.add(target_name)
            target_documents = [
                str(target["document"]),
                *(str(value) for value in target["additional_documents"]),
            ]
            changed_sources = sorted(set(target_documents).intersection(changed_program_documents))
            reasons: list[str] = []
            if name in changed_test_targets:
                reasons.append("test_definition_changed")
            if target_name in changed_build_targets:
                reasons.append("build_target_changed")
            if changed_sources:
                reasons.append("source_changed")
                covered_changed_program_documents.update(changed_sources)
            if not reasons:
                continue
            impacted_tests.append(
                {
                    "name": name,
                    "definition_hash": definition["definition_hash"],
                    "build_target": target_name,
                    "reasons": [reason for reason in _REASON_ORDER if reason in reasons],
                    "build_target_documents": target_documents,
                    "changed_source_documents": changed_sources,
                    "detail": {
                        "tool": "test_target_get",
                        "arguments": {
                            "project": project,
                            "name": name,
                            "branch": branch,
                            "revision_id": target_revision,
                        },
                    },
                }
            )

        removed_test_targets = sorted(set(base_tests).difference(target_tests))
        removed_build_targets = sorted(set(base_targets).difference(target_targets))
        uncovered_changed_program_documents = sorted(
            set(changed_program_documents).difference(covered_changed_program_documents)
        )
        untested_changed_build_targets = sorted(
            set(changed_build_targets)
            .intersection(target_targets)
            .difference(referenced_target_names)
        )
        base_state_hash = self._hash_json(base_state)
        target_state_hash = self._hash_json(target_state)
        plan_identity = {
            "format": TEST_IMPACT_PLAN_FORMAT,
            "project": project,
            "branch": branch,
            "base_revision_id": base_revision_id,
            "target_revision_id": target_revision,
            "base_state_hash": base_state_hash,
            "target_state_hash": target_state_hash,
            "changed_program_documents": changed_program_documents,
            "changed_build_targets": changed_build_targets,
            "changed_test_targets": changed_test_targets,
            "removed_test_targets": removed_test_targets,
            "removed_build_targets": removed_build_targets,
            "uncovered_changed_program_documents": uncovered_changed_program_documents,
            "untested_changed_build_targets": untested_changed_build_targets,
            "impacted_tests": impacted_tests,
        }
        plan_id = self._hash_json(plan_identity)

        remaining_entries = impacted_tests
        if start_after_name is not None:
            remaining_entries = [item for item in impacted_tests if item["name"] > start_after_name]
        returned_entries = remaining_entries[:limit]
        remaining_count = len(remaining_entries) - len(returned_entries)
        complete_selection = start_after_name is None and remaining_count == 0
        batch_arguments = (
            {
                "project": project,
                "test_targets": [item["name"] for item in impacted_tests],
                "branch": branch,
                "revision_id": target_revision,
            }
            if complete_selection and impacted_tests
            else None
        )
        next_after_name = (
            returned_entries[-1]["name"] if returned_entries and remaining_count > 0 else None
        )
        return {
            "format": TEST_IMPACT_PLAN_FORMAT,
            "plan_id": plan_id,
            "project": project,
            "branch": branch,
            "base_revision_id": base_revision_id,
            "target_revision_id": target_revision,
            "base_state_hash": base_state_hash,
            "target_state_hash": target_state_hash,
            "limits": {
                "limit": limit,
                "evidence_limit": evidence_limit,
            },
            "start_after_name": start_after_name,
            "total_impacted_test_count": len(impacted_tests),
            "remaining_after_cursor_count": len(remaining_entries),
            "returned_impacted_test_count": len(returned_entries),
            "impacted_tests_truncated": remaining_count > 0,
            "next_after_name": next_after_name,
            "impacted_tests": returned_entries,
            "complete_selection": complete_selection,
            "test_batch_run": (
                {"tool": "test_batch_run", "arguments": batch_arguments}
                if batch_arguments is not None
                else None
            ),
            **self._bounded_evidence(
                "changed_program_documents",
                changed_program_documents,
                evidence_limit,
            ),
            **self._bounded_evidence(
                "changed_build_targets",
                changed_build_targets,
                evidence_limit,
            ),
            **self._bounded_evidence(
                "changed_test_targets",
                changed_test_targets,
                evidence_limit,
            ),
            **self._bounded_evidence(
                "removed_test_targets",
                removed_test_targets,
                evidence_limit,
            ),
            **self._bounded_evidence(
                "removed_build_targets",
                removed_build_targets,
                evidence_limit,
            ),
            **self._bounded_evidence(
                "uncovered_changed_program_documents",
                uncovered_changed_program_documents,
                evidence_limit,
            ),
            **self._bounded_evidence(
                "untested_changed_build_targets",
                untested_changed_build_targets,
                evidence_limit,
            ),
            "interpretation": {
                "kind": "structural_candidate_plan",
                "executes_tests": False,
                "claims_correctness": False,
                "claims_complete_semantic_coverage": False,
                "caller_order": "lexical_pagination_only",
            },
        }

    @classmethod
    def _changed_documents(
        cls,
        base_state: dict[str, Any],
        target_state: dict[str, Any],
    ) -> set[str]:
        return {
            document
            for document in set(base_state).union(target_state)
            if document not in base_state
            or document not in target_state
            or cls._hash_json(base_state[document]) != cls._hash_json(target_state[document])
        }

    @staticmethod
    def _bounded_evidence(
        name: str,
        values: list[str],
        limit: int,
    ) -> dict[str, Any]:
        returned = values[:limit]
        return {
            f"{name}_count": len(values),
            f"returned_{name}_count": len(returned),
            f"{name}_truncated": len(returned) < len(values),
            name: returned,
        }

    @staticmethod
    def _validate_limit(name: str, value: Any, *, maximum: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationError(
                "INVALID_TEST_IMPACT_LIMIT",
                f"{name} must be an integer",
            )
        if value < 1 or value > maximum:
            raise ValidationError(
                "INVALID_TEST_IMPACT_LIMIT",
                f"{name} must be between 1 and {maximum}",
            )

    @staticmethod
    def _hash_json(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
