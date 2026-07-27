"""Merge previews that enforce cross-document test-target integrity."""

from __future__ import annotations

from typing import Any

from .errors import ConflictError, ValidationError
from .merge_preview import MergePreviewService as _BaseMergePreviewService
from .test_target_validation import validate_test_target_references


class MergePreviewService(_BaseMergePreviewService):
    """Reject previews and publications that leave dangling test definitions."""

    def _snapshot(
        self,
        project: str,
        target_branch: str,
        source_branch: str,
    ) -> dict[str, Any]:
        snapshot = super()._snapshot(project, target_branch, source_branch)
        merged_state = snapshot.get("_merged_state")
        if snapshot["mergeable"] and isinstance(merged_state, dict):
            validate_test_target_references(merged_state)
        return snapshot

    def merge(
        self,
        project: str,
        target_branch: str,
        source_branch: str,
        *,
        preview_id: str | None = None,
        author: str = "merge-agent",
    ) -> dict[str, Any]:
        """Validate metadata and publish against the exact inspected heads."""

        if preview_id is not None and (
            not isinstance(preview_id, str) or not preview_id
        ):
            raise ValidationError(
                "INVALID_MERGE_PREVIEW_ID",
                "preview_id must be a non-empty string",
            )
        snapshot = self._snapshot(project, target_branch, source_branch)
        if preview_id is not None and preview_id != snapshot["preview_id"]:
            raise ValidationError(
                "STALE_MERGE_PREVIEW",
                "one or both branch heads changed after the merge preview",
            )
        if not snapshot["mergeable"]:
            raise ConflictError(list(snapshot["conflicts"]))

        result = self.workspace.merge(
            project,
            target_branch=target_branch,
            source_branch=source_branch,
            author=author,
            expected_target_head=str(snapshot["target_head_revision_id"]),
            expected_source_head=str(snapshot["source_head_revision_id"]),
        )
        reviewed = snapshot if preview_id is not None else None
        return {
            "revision_id": result.revision_id,
            "target_branch": result.target_branch,
            "source_branch": result.source_branch,
            "changed_symbols": list(result.changed_symbols),
            "preview_id": preview_id,
            "preview_enforced": preview_id is not None,
            "reviewed_base_revision_id": (
                reviewed["base_revision_id"] if reviewed is not None else None
            ),
            "reviewed_target_head_revision_id": (
                reviewed["target_head_revision_id"] if reviewed is not None else None
            ),
            "reviewed_source_head_revision_id": (
                reviewed["source_head_revision_id"] if reviewed is not None else None
            ),
        }
