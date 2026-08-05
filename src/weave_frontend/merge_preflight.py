"""One-call merge preview, impact, coverage, and validation composition."""

from __future__ import annotations

from typing import Any

from .errors import ValidationError
from .merge_impact import MergeTargetImpactService
from .merge_validation_set import MergeValidationSetService
from .revision_limits import MAX_PREFLIGHT_IMPACT_TARGETS

MERGE_PREFLIGHT_FORMAT = "weave-merge-preflight-v1"


class MergePreflightService:
    """Compose all non-mutating merge review gates into one deterministic result."""

    def __init__(
        self,
        impacts: MergeTargetImpactService,
        validation_sets: MergeValidationSetService,
        policies: Any | None = None,
    ) -> None:
        self.impacts = impacts
        self.validation_sets = validation_sets
        self.policies = policies

    def run(
        self,
        project: str,
        target_branch: str,
        source_branch: str,
        *,
        preview_id: str | None = None,
        allow_uncovered_documents: bool = False,
    ) -> dict[str, Any]:
        """Return a bounded exact-candidate review artifact without mutation."""

        policy_context = (
            self.policies.compare(project, target_branch, source_branch)
            if self.policies is not None
            else None
        )
        target_policy = policy_context["target"] if policy_context is not None else None
        if (
            allow_uncovered_documents
            and target_policy is not None
            and target_policy["allow_uncovered_documents"] is not True
        ):
            raise ValidationError(
                "MERGE_POLICY_VIOLATION",
                "target merge policy forbids uncovered-document overrides",
            )

        impact = self.impacts.page(
            project,
            target_branch,
            source_branch,
            preview_id=preview_id,
            start_index=0,
            limit=MAX_PREFLIGHT_IMPACT_TARGETS,
        )
        validation_kwargs: dict[str, Any] = {
            "preview_id": str(impact["preview_id"]),
            "allow_uncovered_documents": allow_uncovered_documents,
        }
        if target_policy is not None:
            validation_kwargs["max_target_validations"] = int(target_policy["max_affected_targets"])
        validation_set = self.validation_sets.validate(
            project,
            target_branch,
            source_branch,
            **validation_kwargs,
        )
        impact_summary = {
            key: impact[key]
            for key in (
                "format",
                "changed_program_documents",
                "changed_target_documents",
                "candidate_covered_changed_documents",
                "uncovered_changed_documents",
                "total_target_count_before",
                "total_target_count_after",
                "total_affected_target_count",
                "unaffected_target_count",
                "returned_count",
                "has_more",
                "next_index",
                "affected_targets",
            )
        }
        impact_summary["truncated"] = bool(impact.get("truncated", impact["has_more"]))
        impact_summary["limits"] = impact.get(
            "limits",
            {"maximum_page_size": MAX_PREFLIGHT_IMPACT_TARGETS},
        )
        identity_payload = {
            "format": MERGE_PREFLIGHT_FORMAT,
            "project": project,
            "target_branch": target_branch,
            "source_branch": source_branch,
            "preview_id": impact["preview_id"],
            "merged_root_hash": impact["merged_root_hash"],
            "impact_limit": MAX_PREFLIGHT_IMPACT_TARGETS,
            "impact_total_affected_target_count": impact["total_affected_target_count"],
            "impact_returned_target_count": impact["returned_count"],
            "impact_truncated": impact["has_more"],
            "validation_set_id": validation_set["validation_set_id"],
            "allow_uncovered_documents": allow_uncovered_documents,
            "target_policy_hash": (
                target_policy["policy_hash"] if target_policy is not None else None
            ),
            "source_policy_hash": (
                policy_context["source"]["policy_hash"] if policy_context is not None else None
            ),
            "source_policy_ignored": (
                policy_context["source_policy_ignored"] if policy_context is not None else False
            ),
        }
        preflight_id = self.validation_sets.validations.workspace.db.hash_value(identity_payload)
        publication_arguments = {
            "project": project,
            "target_branch": target_branch,
            "source_branch": source_branch,
            "preview_id": impact["preview_id"],
            "validate_affected_targets": True,
            "allow_uncovered_documents": allow_uncovered_documents,
        }
        if policy_context is not None:
            publication_arguments["preflight_id"] = preflight_id

        result = {
            "format": MERGE_PREFLIGHT_FORMAT,
            "preflight_id": preflight_id,
            "project": project,
            "target_branch": target_branch,
            "source_branch": source_branch,
            "preview_id": impact["preview_id"],
            "base_revision_id": impact["base_revision_id"],
            "target_head_revision_id": impact["target_head_revision_id"],
            "source_head_revision_id": impact["source_head_revision_id"],
            "merged_root_hash": impact["merged_root_hash"],
            "allow_uncovered_documents": allow_uncovered_documents,
            "ready_for_publication": validation_set["ready_for_publication"],
            "impact_limit": MAX_PREFLIGHT_IMPACT_TARGETS,
            "limits": {
                "maximum_presented_impact_targets": MAX_PREFLIGHT_IMPACT_TARGETS,
            },
            "impact": impact_summary,
            "impact_targets_truncated": impact["has_more"],
            "validation_set": validation_set,
            "publication_tool": "branch_merge",
            "publication_arguments": publication_arguments,
        }
        if policy_context is not None:
            result.update(
                {
                    "target_merge_policy": policy_context["target"],
                    "source_merge_policy": policy_context["source"],
                    "source_policy_ignored": policy_context["source_policy_ignored"],
                }
            )
        return result
