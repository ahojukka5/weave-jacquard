"""Structural behavioral-test impact plans for exact virtual merge candidates."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .errors import ConflictError, ValidationError
from .project_metadata import BUILD_TARGET_PREFIX, TEST_TARGET_PREFIX
from .test_impact import (
    DEFAULT_TEST_IMPACT_EVIDENCE_LIMIT,
    DEFAULT_TEST_IMPACT_PAGE_SIZE,
    MAX_TEST_IMPACT_EVIDENCE_LIMIT,
    MAX_TEST_IMPACT_PAGE_SIZE,
)

MERGE_TEST_IMPACT_PLAN_FORMAT = "weave-merge-test-impact-plan-v1"
_REASON_ORDER = (
    "test_definition_changed",
    "build_target_changed",
    "source_changed",
)


class MergeCandidateTestImpactService:
    """Explain affected tests in one exact clean in-memory merge candidate."""

    def __init__(self, previews: Any, build_targets: Any, tests: Any) -> None:
        self.previews = previews
        self.workspace = previews.workspace
        self.build_targets = build_targets
        self.tests = tests

    def page(
        self,
        project: str,
        target_branch: str,
        source_branch: str,
        *,
        preview_id: str | None = None,
        start_after_name: str | None = None,
        limit: int = DEFAULT_TEST_IMPACT_PAGE_SIZE,
        evidence_limit: int = DEFAULT_TEST_IMPACT_EVIDENCE_LIMIT,
    ) -> dict[str, Any]:
        """Return one lexical page for an exact structurally clean merge candidate."""

        self._validate_limit("limit", limit, MAX_TEST_IMPACT_PAGE_SIZE)
        self._validate_limit(
            "evidence_limit",
            evidence_limit,
            MAX_TEST_IMPACT_EVIDENCE_LIMIT,
        )
        if start_after_name is not None:
            self.tests._validate_name(start_after_name)

        candidate = self.previews.candidate(project, target_branch, source_branch)
        if preview_id is not None and preview_id != candidate["preview_id"]:
            raise ValidationError(
                "STALE_MERGE_PREVIEW",
                "one or both branch heads changed after the merge preview",
            )
        if not candidate["mergeable"]:
            raise ConflictError(list(candidate["conflicts"]))

        target_state = self.workspace._state_at_revision(
            candidate["target_head_revision_id"]
        )
        merged_state = candidate.get("_merged_state")
        if not isinstance(merged_state, dict):
            raise ValidationError(
                "INVALID_MERGE_CANDIDATE",
                "clean merge preview did not retain an in-memory candidate state",
            )
        changed_documents = self._changed_documents(target_state, merged_state)
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

        target_targets = self._targets_from_state(target_state)
        candidate_targets = self._targets_from_state(merged_state)
        target_tests = self._tests_from_state(target_state)
        candidate_tests = self._tests_from_state(merged_state)

        impacted_tests: list[dict[str, Any]] = []
        covered_changed_program_documents: set[str] = set()
        referenced_target_names: set[str] = set()
        for name in sorted(candidate_tests):
            definition = candidate_tests[name]
            target_name = str(definition["build_target"])
            target = candidate_targets[target_name]
            referenced_target_names.add(target_name)
            target_documents = [
                str(target["document"]),
                *(str(value) for value in target["additional_documents"]),
            ]
            changed_sources = sorted(
                set(target_documents).intersection(changed_program_documents)
            )
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
                    "definition_subject": {
                        "kind": "virtual_merge_candidate",
                        "preview_id": candidate["preview_id"],
                        "committed_revision_id": None,
                    },
                }
            )

        removed_test_targets = sorted(set(target_tests).difference(candidate_tests))
        removed_build_targets = sorted(set(target_targets).difference(candidate_targets))
        uncovered_changed_program_documents = sorted(
            set(changed_program_documents).difference(covered_changed_program_documents)
        )
        untested_changed_build_targets = sorted(
            set(changed_build_targets)
            .intersection(candidate_targets)
            .difference(referenced_target_names)
        )
        plan_identity = {
            "format": MERGE_TEST_IMPACT_PLAN_FORMAT,
            "project": project,
            "target_branch": target_branch,
            "source_branch": source_branch,
            "preview_id": candidate["preview_id"],
            "target_head_revision_id": candidate["target_head_revision_id"],
            "source_head_revision_id": candidate["source_head_revision_id"],
            "base_revision_id": candidate["base_revision_id"],
            "merged_root_hash": candidate["merged_root_hash"],
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
            remaining_entries = [
                item for item in impacted_tests if item["name"] > start_after_name
            ]
        returned_entries = remaining_entries[:limit]
        remaining_count = len(remaining_entries) - len(returned_entries)
        next_after_name = (
            returned_entries[-1]["name"]
            if returned_entries and remaining_count > 0
            else None
        )
        return {
            "format": MERGE_TEST_IMPACT_PLAN_FORMAT,
            "plan_id": plan_id,
            "project": project,
            "target_branch": target_branch,
            "source_branch": source_branch,
            "preview_id": candidate["preview_id"],
            "target_head_revision_id": candidate["target_head_revision_id"],
            "source_head_revision_id": candidate["source_head_revision_id"],
            "base_revision_id": candidate["base_revision_id"],
            "merged_root_hash": candidate["merged_root_hash"],
            "limits": {"limit": limit, "evidence_limit": evidence_limit},
            "start_after_name": start_after_name,
            "total_impacted_test_count": len(impacted_tests),
            "remaining_after_cursor_count": len(remaining_entries),
            "returned_impacted_test_count": len(returned_entries),
            "impacted_tests_truncated": remaining_count > 0,
            "next_after_name": next_after_name,
            "impacted_tests": returned_entries,
            "complete_selection": start_after_name is None and remaining_count == 0,
            "candidate_execution": None,
            **self._bounded_evidence(
                "changed_program_documents", changed_program_documents, evidence_limit
            ),
            **self._bounded_evidence(
                "changed_build_targets", changed_build_targets, evidence_limit
            ),
            **self._bounded_evidence(
                "changed_test_targets", changed_test_targets, evidence_limit
            ),
            **self._bounded_evidence(
                "removed_test_targets", removed_test_targets, evidence_limit
            ),
            **self._bounded_evidence(
                "removed_build_targets", removed_build_targets, evidence_limit
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
                "kind": "virtual_merge_structural_candidate_plan",
                "executes_tests": False,
                "publishes_merge": False,
                "claims_correctness": False,
                "claims_complete_semantic_coverage": False,
                "ordinary_test_batch_compatible": False,
                "caller_order": "lexical_pagination_only",
            },
        }

    def _targets_from_state(self, state: dict[str, Any]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for document, root in sorted(state.items()):
            if not document.startswith(BUILD_TARGET_PREFIX):
                continue
            name = document[len(BUILD_TARGET_PREFIX) :]
            config = self.build_targets._parse_tree(root, name=name)
            self.build_targets._require_program_documents(
                state,
                [config["document"], *config["additional_documents"]],
            )
            result[name] = config
        return result

    def _tests_from_state(self, state: dict[str, Any]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for document, root in sorted(state.items()):
            if not document.startswith(TEST_TARGET_PREFIX):
                continue
            name = document[len(TEST_TARGET_PREFIX) :]
            config = self.tests._parse_tree(root, name=name)
            self.tests._require_build_target(state, str(config["build_target"]))
            result[name] = {
                **config,
                "definition_hash": self.workspace.db.hash_value(root),
            }
        return result

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
            or cls._hash_json(base_state[document])
            != cls._hash_json(target_state[document])
        }

    @staticmethod
    def _bounded_evidence(name: str, values: list[str], limit: int) -> dict[str, Any]:
        returned = values[:limit]
        return {
            f"{name}_count": len(values),
            f"returned_{name}_count": len(returned),
            f"{name}_truncated": len(returned) < len(values),
            name: returned,
        }

    @staticmethod
    def _validate_limit(name: str, value: Any, maximum: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationError(
                "INVALID_MERGE_TEST_IMPACT_LIMIT",
                f"{name} must be an integer",
            )
        if value < 1 or value > maximum:
            raise ValidationError(
                "INVALID_MERGE_TEST_IMPACT_LIMIT",
                f"{name} must be between 1 and {maximum}",
            )

    @staticmethod
    def _hash_json(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
