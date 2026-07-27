"""Merge impact analysis that separates source, build, and test metadata."""

from __future__ import annotations

from typing import Any

from .errors import ConflictError, ValidationError
from .merge_impact import MERGE_TARGET_IMPACT_FORMAT
from .merge_impact import MergeTargetImpactService as _Base
from .project_metadata import (
    BUILD_TARGET_PREFIX,
    TEST_TARGET_PREFIX,
    is_project_metadata_document,
)


class MergeTargetImpactService(_Base):
    """Explain build-target impact without compiling revisioned test metadata."""

    def analyze(
        self,
        project: str,
        target_branch: str,
        source_branch: str,
        *,
        preview_id: str | None = None,
    ) -> dict[str, Any]:
        self._validate_preview_id(preview_id)
        candidate = self.previews.candidate(project, target_branch, source_branch)
        if preview_id is not None and preview_id != candidate["preview_id"]:
            raise ValidationError(
                "STALE_MERGE_PREVIEW",
                "one or both branch heads changed after the merge preview",
            )
        if not candidate["mergeable"]:
            raise ConflictError(list(candidate["conflicts"]))

        merged_state = candidate.get("_merged_state")
        if not isinstance(merged_state, dict):
            raise ValidationError(
                "INVALID_MERGE_CANDIDATE",
                "clean merge preview did not retain an in-memory candidate state",
            )
        target_state = self.previews.workspace._state_at_revision(
            str(candidate["target_head_revision_id"])
        )
        changed_documents = {
            str(change["document"]) for change in candidate["document_changes"]
        }
        changed_program_documents = sorted(
            name for name in changed_documents if not is_project_metadata_document(name)
        )
        changed_target_documents = sorted(
            name for name in changed_documents if name.startswith(BUILD_TARGET_PREFIX)
        )
        changed_test_documents = sorted(
            name for name in changed_documents if name.startswith(TEST_TARGET_PREFIX)
        )

        before_targets = self._targets(target_state)
        after_targets = self._targets(merged_state)
        affected = self._affected_targets(
            before_targets,
            after_targets,
            set(changed_program_documents),
        )
        affected_candidate_names = {
            str(item["name"]) for item in affected if item["after"] is not None
        }
        candidate_covered_documents = sorted(
            {
                document
                for config in after_targets.values()
                for document in self._documents(config)
            }
            & set(changed_program_documents)
        )
        uncovered = sorted(
            set(changed_program_documents) - set(candidate_covered_documents)
        )
        return {
            "format": MERGE_TARGET_IMPACT_FORMAT,
            "project": project,
            "target_branch": target_branch,
            "source_branch": source_branch,
            "preview_id": candidate["preview_id"],
            "base_revision_id": candidate["base_revision_id"],
            "target_head_revision_id": candidate["target_head_revision_id"],
            "source_head_revision_id": candidate["source_head_revision_id"],
            "merged_root_hash": candidate["merged_root_hash"],
            "changed_program_documents": changed_program_documents,
            "changed_target_documents": changed_target_documents,
            "changed_test_documents": changed_test_documents,
            "candidate_covered_changed_documents": candidate_covered_documents,
            "uncovered_changed_documents": uncovered,
            "total_target_count_before": len(before_targets),
            "total_target_count_after": len(after_targets),
            "total_affected_target_count": len(affected),
            "unaffected_target_count": len(after_targets) - len(affected_candidate_names),
            "affected_targets": affected,
        }
