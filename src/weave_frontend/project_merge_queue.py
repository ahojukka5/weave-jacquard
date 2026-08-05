"""Stable bounded project merge queues over exact branch-head catalogs."""

from __future__ import annotations

from typing import Any

from .errors import ValidationError
from .merge_preview import MergePreviewService
from .project_agent_status import (
    MAX_AGENT_STATUS_CHECKPOINT_SCAN,
    ProjectAgentStatusService,
)
from .project_merge_catalog import (
    PROJECT_MERGE_CATALOG_FORMAT,
    ProjectMergeCatalogService,
)
from .revision_limits import (
    MAX_PROJECT_MERGE_QUEUE_CONFLICTS,
    MAX_PROJECT_MERGE_QUEUE_DOCUMENTS,
    MAX_PROJECT_MERGE_QUEUE_PAGE,
    require_bounded_int,
)

PROJECT_MERGE_QUEUE_FORMAT = "weave-project-merge-queue-v1"
PROJECT_MERGE_QUEUE_CATALOG_FORMAT = PROJECT_MERGE_CATALOG_FORMAT


class ProjectMergeQueueService:
    """Page compact exact-head merge previews for project source branches."""

    def __init__(
        self,
        previews: MergePreviewService,
        statuses: ProjectAgentStatusService,
        catalogs: ProjectMergeCatalogService | None = None,
    ) -> None:
        self.previews = previews
        self.statuses = statuses
        self.workspace = previews.workspace
        self.catalogs = catalogs or ProjectMergeCatalogService(self.workspace)

    def page(
        self,
        project: str,
        target_branch: str = "main",
        *,
        start_after_source: str | None = None,
        catalog_id: str | None = None,
        limit: int = 10,
        checkpoint_scan_limit: int = 100,
        conflict_limit: int = 20,
        changed_document_limit: int = 50,
    ) -> dict[str, Any]:
        """Return one stable lexical page of compact source-to-target previews."""

        self._validate_limit("limit", limit, MAX_PROJECT_MERGE_QUEUE_PAGE)
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
        self._validate_optional_id("catalog_id", catalog_id)
        self._validate_optional_id("start_after_source", start_after_source)

        catalog = self.catalogs.capture(
            project,
            target_branch,
            invalid_target_code="INVALID_MERGE_QUEUE_TARGET",
        )
        target = catalog["target"]
        sources = catalog["sources"]
        effective_catalog_id = catalog["catalog_id"]
        if catalog_id is not None and catalog_id != effective_catalog_id:
            raise ValidationError(
                "STALE_PROJECT_MERGE_QUEUE_CATALOG",
                "project branch heads changed since the requested merge-queue catalog",
            )

        source_names = [member["branch"] for member in sources]
        if start_after_source is None:
            start_index = 0
        else:
            try:
                start_index = source_names.index(start_after_source) + 1
            except ValueError as exc:
                raise ValidationError(
                    "INVALID_MERGE_QUEUE_CURSOR",
                    "start_after_source must identify a source branch in the catalog",
                ) from exc
        selected = sources[start_index : start_index + limit]
        entries = [
            self._entry(
                project,
                target,
                source,
                checkpoint_scan_limit=checkpoint_scan_limit,
                conflict_limit=conflict_limit,
                changed_document_limit=changed_document_limit,
            )
            for source in selected
        ]
        end_index = start_index + len(selected)
        has_more = end_index < len(sources)
        result: dict[str, Any] = {
            "format": PROJECT_MERGE_QUEUE_FORMAT,
            "project": project,
            "target_branch": target_branch,
            "target_head_revision_id": target["head_revision_id"],
            "catalog_id": effective_catalog_id,
            "source_catalog_count": len(sources),
            "start_after_source": start_after_source,
            "limit": limit,
            "checkpoint_scan_limit": checkpoint_scan_limit,
            "conflict_limit": conflict_limit,
            "changed_document_limit": changed_document_limit,
            "returned_source_count": len(entries),
            "has_more": has_more,
            "truncated": has_more,
            "next_after_source": selected[-1]["branch"] if has_more and selected else None,
            "limits": {
                "maximum_page_size": MAX_PROJECT_MERGE_QUEUE_PAGE,
                "maximum_checkpoint_scan": MAX_AGENT_STATUS_CHECKPOINT_SCAN,
                "maximum_conflicts_per_source": MAX_PROJECT_MERGE_QUEUE_CONFLICTS,
                "maximum_changed_documents_per_source": (MAX_PROJECT_MERGE_QUEUE_DOCUMENTS),
            },
            "sources": entries,
            "ordering": "lexical source branch name within one exact branch-head catalog",
            "readiness_note": (
                "mergeable means structural preview success only; policy, coverage, "
                "compiler validation, and publication heads must still be checked by "
                "branch_merge_preflight"
            ),
            "priority_note": (
                "lexical order is deterministic pagination and does not represent merge "
                "priority, urgency, age, quality, or readiness"
            ),
        }
        result["page_id"] = self.workspace.db.hash_value(result)
        return result

    def _entry(
        self,
        project: str,
        target: dict[str, str],
        source: dict[str, str],
        *,
        checkpoint_scan_limit: int,
        conflict_limit: int,
        changed_document_limit: int,
    ) -> dict[str, Any]:
        preview = self.previews.preview(
            project,
            target["branch"],
            source["branch"],
        )
        if (
            preview["target_head_revision_id"] != target["head_revision_id"]
            or preview["source_head_revision_id"] != source["head_revision_id"]
        ):
            raise ValidationError(
                "STALE_PROJECT_MERGE_QUEUE_CATALOG",
                "a target or source branch advanced while composing the merge queue",
            )
        conflicts = list(preview["conflicts"])
        changed_documents = list(preview["changed_documents"])
        mergeable = bool(preview["mergeable"])
        if not mergeable:
            classification = "conflicted"
        elif changed_documents:
            classification = "clean_changes"
        else:
            classification = "clean_no_changes"
        source_status = self.statuses._branch_status(
            project,
            source,
            checkpoint_scan_limit=checkpoint_scan_limit,
        )
        return {
            "source_branch": source["branch"],
            "source_head_revision_id": source["head_revision_id"],
            "base_revision_id": preview["base_revision_id"],
            "preview_id": preview["preview_id"],
            "classification": classification,
            "mergeable": mergeable,
            "conflict_count": len(conflicts),
            "conflicts": conflicts[:conflict_limit],
            "conflicts_truncated": len(conflicts) > conflict_limit,
            "changed_document_count": len(changed_documents),
            "changed_documents": changed_documents[:changed_document_limit],
            "changed_documents_truncated": (len(changed_documents) > changed_document_limit),
            "target_root_hash": preview["target_root_hash"],
            "source_root_hash": preview["source_root_hash"],
            "merged_root_hash": preview["merged_root_hash"],
            "source_checkpoint": {
                key: source_status[key]
                for key in (
                    "checkpoint_state",
                    "checkpoint_is_head",
                    "checkpoint",
                    "revisions_scanned",
                    "revisions_since_checkpoint",
                    "checkpoint_scan_limit_reached",
                    "complete_first_parent_history_scanned",
                    "checkpoint_lag_lower_bound",
                    "program_state_changed_since_checkpoint",
                )
            },
            "full_preview": {
                "tool": "branch_merge_preview",
                "arguments": {
                    "project": project,
                    "target_branch": target["branch"],
                    "source_branch": source["branch"],
                },
            },
            "preflight": (
                {
                    "tool": "branch_merge_preflight",
                    "arguments": {
                        "project": project,
                        "target_branch": target["branch"],
                        "source_branch": source["branch"],
                        "preview_id": preview["preview_id"],
                    },
                }
                if mergeable
                else None
            ),
        }

    def _catalog_members(self, project_id: str) -> list[dict[str, str]]:
        """Compatibility delegate for older internal callers."""

        return self.catalogs.members(project_id)

    @staticmethod
    def _validate_limit(name: str, value: Any, maximum: int) -> None:
        require_bounded_int(
            value,
            code="INVALID_PROJECT_MERGE_QUEUE_LIMIT",
            name=name,
            minimum=1,
            maximum=maximum,
        )

    @staticmethod
    def _validate_optional_id(name: str, value: Any) -> None:
        if value is not None and (not isinstance(value, str) or not value):
            raise ValidationError(
                "INVALID_MERGE_QUEUE_CURSOR",
                f"{name} must be a non-empty string or null",
            )
