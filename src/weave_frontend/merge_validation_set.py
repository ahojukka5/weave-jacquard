"""Bounded validation sets for every affected surviving merge target."""

from __future__ import annotations

from typing import Any

from .errors import ValidationError
from .merge_impact import MergeTargetImpactService
from .merge_validation import MergeValidationService

MERGE_VALIDATION_SET_FORMAT = "weave-merge-validation-set-v1"
MAX_AFFECTED_TARGET_VALIDATIONS = 64


class MergeValidationSetService:
    """Validate every affected target that exists in an exact merge candidate."""

    def __init__(
        self,
        impacts: MergeTargetImpactService,
        validations: MergeValidationService,
    ) -> None:
        self.impacts = impacts
        self.validations = validations

    def validate(
        self,
        project: str,
        target_branch: str,
        source_branch: str,
        *,
        preview_id: str | None = None,
        allow_uncovered_documents: bool = False,
        max_target_validations: int = MAX_AFFECTED_TARGET_VALIDATIONS,
    ) -> dict[str, Any]:
        """Return deterministic validation evidence for all affected candidate targets."""

        if not isinstance(allow_uncovered_documents, bool):
            raise ValidationError(
                "INVALID_UNCOVERED_DOCUMENT_POLICY",
                "allow_uncovered_documents must be a boolean",
            )
        self._validate_max_target_validations(max_target_validations)

        impact = self.impacts.analyze(
            project,
            target_branch,
            source_branch,
            preview_id=preview_id,
        )
        surviving = [item for item in impact["affected_targets"] if item["after"] is not None]
        removed = [
            str(item["name"]) for item in impact["affected_targets"] if item["after"] is None
        ]
        if len(surviving) > max_target_validations:
            raise ValidationError(
                "TOO_MANY_AFFECTED_TARGETS",
                "prospective merge affects "
                f"{len(surviving)} surviving targets; maximum is "
                f"{max_target_validations}",
            )

        uncovered = list(impact["uncovered_changed_documents"])
        coverage_passed = allow_uncovered_documents or not uncovered
        validation_records: list[dict[str, Any]] = []
        if coverage_passed:
            for item in surviving:
                result = self.validations.validate(
                    project,
                    target_branch,
                    source_branch,
                    str(item["name"]),
                    preview_id=str(impact["preview_id"]),
                )
                validation_records.append(self._compact(result, item))

        unavailable = [
            str(item["target"]) for item in validation_records if item["available"] is not True
        ]
        invalid = [
            str(item["target"])
            for item in validation_records
            if item["available"] is True and item["valid"] is not True
        ]
        passed = [
            str(item["target"])
            for item in validation_records
            if item["available"] is True and item["valid"] is True
        ]
        ready = (
            coverage_passed
            and len(validation_records) == len(surviving)
            and not unavailable
            and not invalid
        )
        payload = {
            "format": MERGE_VALIDATION_SET_FORMAT,
            "preview_id": impact["preview_id"],
            "merged_root_hash": impact["merged_root_hash"],
            "allow_uncovered_documents": allow_uncovered_documents,
            "max_target_validations": max_target_validations,
            "uncovered_changed_documents": uncovered,
            "affected_surviving_targets": [str(item["name"]) for item in surviving],
            "skipped_removed_targets": removed,
            "validation_ids": [str(item["validation_id"]) for item in validation_records],
        }
        validation_set_id = self.validations.workspace.db.hash_value(payload)
        return {
            "format": MERGE_VALIDATION_SET_FORMAT,
            "validation_set_id": validation_set_id,
            "project": project,
            "target_branch": target_branch,
            "source_branch": source_branch,
            "preview_id": impact["preview_id"],
            "base_revision_id": impact["base_revision_id"],
            "target_head_revision_id": impact["target_head_revision_id"],
            "source_head_revision_id": impact["source_head_revision_id"],
            "merged_root_hash": impact["merged_root_hash"],
            "impact_format": impact["format"],
            "changed_program_documents": impact["changed_program_documents"],
            "candidate_covered_changed_documents": impact["candidate_covered_changed_documents"],
            "uncovered_changed_documents": uncovered,
            "allow_uncovered_documents": allow_uncovered_documents,
            "max_target_validations": max_target_validations,
            "coverage_passed": coverage_passed,
            "affected_target_count": impact["total_affected_target_count"],
            "affected_surviving_target_count": len(surviving),
            "affected_surviving_targets": [str(item["name"]) for item in surviving],
            "skipped_removed_targets": removed,
            "validated_target_count": len(validation_records),
            "passed_target_count": len(passed),
            "failed_target_count": len(invalid),
            "unavailable_target_count": len(unavailable),
            "passed_targets": passed,
            "failed_targets": invalid,
            "unavailable_targets": unavailable,
            "ready_for_publication": ready,
            "target_validations": validation_records,
        }

    @staticmethod
    def require_ready(result: dict[str, Any]) -> None:
        """Reject merge publication unless the complete validation set passed."""

        if result.get("coverage_passed") is not True:
            documents = result.get("uncovered_changed_documents") or []
            raise ValidationError(
                "MERGE_UNCOVERED_DOCUMENTS",
                "changed program documents have no surviving target coverage: "
                + ", ".join(map(str, documents)),
            )
        unavailable = result.get("unavailable_targets") or []
        if unavailable:
            raise ValidationError(
                "MERGE_VALIDATION_UNAVAILABLE",
                "compiler validation unavailable for affected targets: "
                + ", ".join(map(str, unavailable)),
            )
        failed = result.get("failed_targets") or []
        if failed:
            raise ValidationError(
                "MERGE_VALIDATION_FAILED",
                "prospective merge failed affected-target validation: "
                + ", ".join(map(str, failed)),
            )
        if result.get("ready_for_publication") is not True:
            raise ValidationError(
                "INCOMPLETE_MERGE_VALIDATION_SET",
                "not every affected surviving target produced a passing validation",
            )

    @staticmethod
    def _validate_max_target_validations(value: int) -> None:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 1
            or value > MAX_AFFECTED_TARGET_VALIDATIONS
        ):
            raise ValidationError(
                "INVALID_AFFECTED_TARGET_LIMIT",
                f"max_target_validations must be between 1 and {MAX_AFFECTED_TARGET_VALIDATIONS}",
            )

    @staticmethod
    def _compact(
        result: dict[str, Any],
        impact: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "target": result["build_target"]["name"],
            "affected_reasons": list(impact["affected_reasons"]),
            "changed_source_documents": list(impact["changed_source_documents"]),
            "validation_id": result["validation_id"],
            "documents": list(result["documents"]),
            "compiler_sha256": result["compiler"]["sha256"],
            "available": result["available"],
            "valid": result["valid"],
            "returncode": result["returncode"],
            "timed_out": result["timed_out"],
            "diagnostic": result["diagnostic"],
            "stderr": result["stderr"],
            "stderr_truncated": result["stderr_truncated"],
            "wir_sha256": result["wir_sha256"],
            "wir_bytes": result["wir_bytes"],
        }
