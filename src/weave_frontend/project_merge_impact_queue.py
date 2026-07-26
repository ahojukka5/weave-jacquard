"""Stable bounded project merge-impact queues without compiler execution."""

from __future__ import annotations

from typing import Any

from .errors import ValidationError
from .merge_impact import (
    MAX_MERGE_TARGET_IMPACT_PAGE_SIZE,
    MergeTargetImpactService,
)
from .merge_policy import MergePolicyRegistry
from .project_agent_status import MAX_AGENT_STATUS_CHECKPOINT_SCAN
from .project_merge_queue import (
    MAX_PROJECT_MERGE_QUEUE_CONFLICTS,
    MAX_PROJECT_MERGE_QUEUE_DOCUMENTS,
    ProjectMergeQueueService,
)

PROJECT_MERGE_IMPACT_QUEUE_FORMAT = "weave-project-merge-impact-queue-v1"
MAX_PROJECT_MERGE_IMPACT_QUEUE_PAGE = 10
MAX_PROJECT_MERGE_IMPACT_QUEUE_DOCUMENTS = 200


class ProjectMergeImpactQueueService:
    """Compose exact-head merge, coverage, and policy evidence without compiling."""

    def __init__(
        self,
        queues: ProjectMergeQueueService,
        impacts: MergeTargetImpactService,
        policies: MergePolicyRegistry,
    ) -> None:
        self.queues = queues
        self.impacts = impacts
        self.policies = policies
        self.workspace = queues.workspace

    def page(
        self,
        project: str,
        target_branch: str = "main",
        *,
        start_after_source: str | None = None,
        catalog_id: str | None = None,
        limit: int = 5,
        checkpoint_scan_limit: int = 100,
        conflict_limit: int = 20,
        changed_document_limit: int = 50,
        affected_target_limit: int = 50,
        coverage_document_limit: int = 100,
    ) -> dict[str, Any]:
        """Return one stable page of structural, coverage, and policy evidence."""

        self._validate_limit(
            "limit",
            limit,
            MAX_PROJECT_MERGE_IMPACT_QUEUE_PAGE,
        )
        self._validate_limit(
            "checkpoint_scan_limit",
            checkpoint_scan_limit,
            MAX_AGENT_STATUS_CHECKPOINT_SCAN,
        )
        self._validate_limit(
            "conflict_limit",
            conflict_limit,
            MAX_PROJECT_MERGE_QUEUE_CONFLICTS,
        )
        self._validate_limit(
            "changed_document_limit",
            changed_document_limit,
            MAX_PROJECT_MERGE_QUEUE_DOCUMENTS,
        )
        self._validate_limit(
            "affected_target_limit",
            affected_target_limit,
            MAX_MERGE_TARGET_IMPACT_PAGE_SIZE,
        )
        self._validate_limit(
            "coverage_document_limit",
            coverage_document_limit,
            MAX_PROJECT_MERGE_IMPACT_QUEUE_DOCUMENTS,
        )

        queue = self.queues.page(
            project,
            target_branch,
            start_after_source=start_after_source,
            catalog_id=catalog_id,
            limit=limit,
            checkpoint_scan_limit=checkpoint_scan_limit,
            conflict_limit=conflict_limit,
            changed_document_limit=changed_document_limit,
        )
        target_policy = self.policies.get(
            project,
            target_branch,
            revision_id=str(queue["target_head_revision_id"]),
        )
        sources = [
            self._source_entry(
                project,
                target_branch,
                queue_entry,
                target_policy=target_policy,
                affected_target_limit=affected_target_limit,
                coverage_document_limit=coverage_document_limit,
            )
            for queue_entry in queue["sources"]
        ]
        result: dict[str, Any] = {
            "format": PROJECT_MERGE_IMPACT_QUEUE_FORMAT,
            "project": project,
            "target_branch": target_branch,
            "target_head_revision_id": queue["target_head_revision_id"],
            "catalog_id": queue["catalog_id"],
            "queue_page_id": queue["page_id"],
            "source_catalog_count": queue["source_catalog_count"],
            "start_after_source": queue["start_after_source"],
            "limit": limit,
            "checkpoint_scan_limit": checkpoint_scan_limit,
            "conflict_limit": conflict_limit,
            "changed_document_limit": changed_document_limit,
            "affected_target_limit": affected_target_limit,
            "coverage_document_limit": coverage_document_limit,
            "returned_source_count": len(sources),
            "has_more": queue["has_more"],
            "next_after_source": queue["next_after_source"],
            "target_merge_policy": target_policy,
            "sources": sources,
            "ordering": queue["ordering"],
            "compiler_note": (
                "no compiler or build validation was run; affected-target and coverage "
                "evidence must be followed by branch_merge_preflight when required"
            ),
            "authority_note": (
                "the exact target revision policy is authoritative; source policy is "
                "visible for review but cannot weaken target admission requirements"
            ),
            "readiness_note": (
                "coverage and policy evidence are non-mutating review inputs and do not "
                "prove compiler correctness, preflight identity, publication-head "
                "stability, human approval, or merge readiness"
            ),
            "priority_note": queue["priority_note"],
        }
        result["page_id"] = self.workspace.db.hash_value(result)
        return result

    def _source_entry(
        self,
        project: str,
        target_branch: str,
        queue_entry: dict[str, Any],
        *,
        target_policy: dict[str, Any],
        affected_target_limit: int,
        coverage_document_limit: int,
    ) -> dict[str, Any]:
        source_branch = str(queue_entry["source_branch"])
        source_head = str(queue_entry["source_head_revision_id"])
        source_policy = self.policies.get(
            project,
            source_branch,
            revision_id=source_head,
        )
        policy_context = {
            "target": target_policy,
            "source": source_policy,
            "source_policy_ignored": (
                target_policy["policy_hash"] != source_policy["policy_hash"]
            ),
        }
        if not queue_entry["mergeable"]:
            return {
                **queue_entry,
                "impact_classification": "conflicted",
                "impact": None,
                "coverage_gate": None,
                "merge_policy": policy_context,
                "impact_call": None,
            }

        try:
            impact = self.impacts.page(
                project,
                target_branch,
                source_branch,
                preview_id=str(queue_entry["preview_id"]),
                start_index=0,
                limit=affected_target_limit,
            )
        except ValidationError as exc:
            if exc.code == "STALE_MERGE_PREVIEW":
                raise ValidationError(
                    "STALE_PROJECT_MERGE_QUEUE_CATALOG",
                    "a target or source branch advanced while composing merge impact",
                ) from exc
            raise
        if (
            impact["target_head_revision_id"]
            != target_policy["revision_id"]
            or impact["source_head_revision_id"] != source_head
            or impact["preview_id"] != queue_entry["preview_id"]
        ):
            raise ValidationError(
                "STALE_PROJECT_MERGE_QUEUE_CATALOG",
                "merge-impact evidence did not match the exact queue catalog heads",
            )

        changed_program = list(impact["changed_program_documents"])
        changed_targets = list(impact["changed_target_documents"])
        covered = list(impact["candidate_covered_changed_documents"])
        uncovered = list(impact["uncovered_changed_documents"])
        if uncovered:
            classification = "uncovered_program_changes"
        elif changed_program:
            classification = "covered_program_changes"
        elif changed_targets:
            classification = "target_definition_changes_only"
        else:
            classification = "no_changes"
        compact_impact = {
            "format": impact["format"],
            "preview_id": impact["preview_id"],
            "merged_root_hash": impact["merged_root_hash"],
            "changed_program_document_count": len(changed_program),
            "changed_program_documents": changed_program[:coverage_document_limit],
            "changed_program_documents_truncated": (
                len(changed_program) > coverage_document_limit
            ),
            "changed_target_document_count": len(changed_targets),
            "changed_target_documents": changed_targets[:coverage_document_limit],
            "changed_target_documents_truncated": (
                len(changed_targets) > coverage_document_limit
            ),
            "covered_changed_document_count": len(covered),
            "covered_changed_documents": covered[:coverage_document_limit],
            "covered_changed_documents_truncated": (
                len(covered) > coverage_document_limit
            ),
            "uncovered_changed_document_count": len(uncovered),
            "uncovered_changed_documents": uncovered[:coverage_document_limit],
            "uncovered_changed_documents_truncated": (
                len(uncovered) > coverage_document_limit
            ),
            "total_target_count_before": impact["total_target_count_before"],
            "total_target_count_after": impact["total_target_count_after"],
            "total_affected_target_count": impact["total_affected_target_count"],
            "unaffected_target_count": impact["unaffected_target_count"],
            "returned_affected_target_count": impact["returned_count"],
            "affected_targets_truncated": impact["has_more"],
            "next_affected_target_index": impact["next_index"],
            "affected_targets": impact["affected_targets"],
        }
        return {
            **queue_entry,
            "impact_classification": classification,
            "impact": compact_impact,
            "coverage_gate": {
                "uncovered_documents_present": bool(uncovered),
                "target_allows_uncovered_documents": target_policy[
                    "allow_uncovered_documents"
                ],
                "override_possible": bool(uncovered)
                and bool(target_policy["allow_uncovered_documents"]),
            },
            "merge_policy": policy_context,
            "impact_call": {
                "tool": "branch_merge_impact",
                "arguments": {
                    "project": project,
                    "target_branch": target_branch,
                    "source_branch": source_branch,
                    "preview_id": queue_entry["preview_id"],
                    "start_index": 0,
                    "limit": affected_target_limit,
                },
            },
        }

    @staticmethod
    def _validate_limit(name: str, value: Any, maximum: int) -> None:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 1
            or value > maximum
        ):
            raise ValidationError(
                "INVALID_PROJECT_MERGE_IMPACT_QUEUE_LIMIT",
                f"{name} must be an integer between 1 and {maximum}",
            )
