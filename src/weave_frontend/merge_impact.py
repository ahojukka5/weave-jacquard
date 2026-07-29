"""Deterministic named-target impact analysis for prospective branch merges."""

from __future__ import annotations

from typing import Any

from .build_targets import BUILD_TARGET_PREFIX, BuildTargetRegistry
from .errors import ConflictError, ValidationError
from .merge_preview import MergePreviewService
from .revision_limits import (
    MAX_MERGE_TARGET_IMPACT_PAGE_SIZE,
    require_bounded_int,
    require_nonnegative_int,
)

MERGE_TARGET_IMPACT_FORMAT = "weave-merge-target-impact-v1"


class MergeTargetImpactService:
    """Explain which named targets a clean prospective merge can affect."""

    def __init__(
        self,
        previews: MergePreviewService,
        targets: BuildTargetRegistry,
    ) -> None:
        self.previews = previews
        self.targets = targets

    def page(
        self,
        project: str,
        target_branch: str,
        source_branch: str,
        *,
        preview_id: str | None = None,
        start_index: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Return one bounded deterministic page of affected named targets."""

        effective_start = require_nonnegative_int(
            start_index,
            code="INVALID_MERGE_TARGET_IMPACT_INDEX",
            name="start_index",
        )
        effective_limit = require_bounded_int(
            limit,
            code="INVALID_MERGE_TARGET_IMPACT_LIMIT",
            name="limit",
            minimum=1,
            maximum=MAX_MERGE_TARGET_IMPACT_PAGE_SIZE,
        )
        result = self.analyze(
            project,
            target_branch,
            source_branch,
            preview_id=preview_id,
        )
        affected = result.pop("affected_targets")
        page = affected[effective_start : effective_start + effective_limit]
        next_index = effective_start + len(page)
        has_more = next_index < len(affected)
        return {
            **result,
            "start_index": effective_start,
            "limit": effective_limit,
            "returned_count": len(page),
            "has_more": has_more,
            "truncated": has_more,
            "next_index": next_index if has_more else None,
            "limits": {
                "maximum_page_size": MAX_MERGE_TARGET_IMPACT_PAGE_SIZE,
            },
            "affected_targets": page,
        }

    def analyze(
        self,
        project: str,
        target_branch: str,
        source_branch: str,
        *,
        preview_id: str | None = None,
    ) -> dict[str, Any]:
        """Return complete deterministic impact data for internal orchestration."""

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
            document
            for document in changed_documents
            if not document.startswith(BUILD_TARGET_PREFIX)
        )
        changed_target_documents = sorted(
            document
            for document in changed_documents
            if document.startswith(BUILD_TARGET_PREFIX)
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
            "candidate_covered_changed_documents": candidate_covered_documents,
            "uncovered_changed_documents": uncovered,
            "total_target_count_before": len(before_targets),
            "total_target_count_after": len(after_targets),
            "total_affected_target_count": len(affected),
            "unaffected_target_count": len(after_targets) - len(affected_candidate_names),
            "affected_targets": affected,
        }

    def _targets(
        self,
        state: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for storage_document, root in sorted(state.items()):
            if not storage_document.startswith(BUILD_TARGET_PREFIX):
                continue
            name = storage_document[len(BUILD_TARGET_PREFIX) :]
            config = self.targets._parse_tree(root, name=name)
            result[name] = {
                key: config[key]
                for key in (
                    "name",
                    "document",
                    "additional_documents",
                    "compiler_target",
                )
            }
        return result

    @classmethod
    def _affected_targets(
        cls,
        before_targets: dict[str, dict[str, Any]],
        after_targets: dict[str, dict[str, Any]],
        changed_program_documents: set[str],
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for name in sorted(set(before_targets) | set(after_targets)):
            before = before_targets.get(name)
            after = after_targets.get(name)
            reasons: list[str] = []
            if before is None:
                status = "added"
                reasons.append("target_added")
            elif after is None:
                status = "removed"
                reasons.append("target_removed")
            elif before != after:
                status = "modified"
                reasons.append("target_definition_changed")
            else:
                status = "unchanged"

            referenced = sorted(
                (set(cls._documents(before)) | set(cls._documents(after)))
                & changed_program_documents
            )
            if referenced:
                reasons.append("source_document_changed")
            if not reasons:
                continue
            result.append(
                {
                    "name": name,
                    "status": status,
                    "affected_reasons": reasons,
                    "changed_source_documents": referenced,
                    "before": before,
                    "after": after,
                }
            )
        return result

    @staticmethod
    def _documents(config: dict[str, Any] | None) -> list[str]:
        if config is None:
            return []
        return [str(config["document"]), *map(str, config["additional_documents"])]

    @staticmethod
    def _validate_preview_id(preview_id: str | None) -> None:
        if preview_id is not None and (
            not isinstance(preview_id, str) or not preview_id
        ):
            raise ValidationError(
                "INVALID_MERGE_PREVIEW_ID",
                "preview_id must be a non-empty string",
            )

    @staticmethod
    def _validate_start_index(start_index: int) -> None:
        require_nonnegative_int(
            start_index,
            code="INVALID_MERGE_TARGET_IMPACT_INDEX",
            name="start_index",
        )

    @staticmethod
    def _validate_limit(limit: int) -> None:
        require_bounded_int(
            limit,
            code="INVALID_MERGE_TARGET_IMPACT_LIMIT",
            name="limit",
            minimum=1,
            maximum=MAX_MERGE_TARGET_IMPACT_PAGE_SIZE,
        )
