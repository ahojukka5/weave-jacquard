"""Stable bounded project merge queues over exact branch-head catalogs."""

from __future__ import annotations

from typing import Any

from .errors import ValidationError
from .merge_preview import MergePreviewService
from .project_agent_status import (
    MAX_AGENT_STATUS_BRANCH_CATALOG,
    ProjectAgentStatusService,
)

PROJECT_MERGE_QUEUE_FORMAT = "weave-project-merge-queue-v1"
PROJECT_MERGE_QUEUE_CATALOG_FORMAT = "weave-project-merge-queue-catalog-v1"
MAX_PROJECT_MERGE_QUEUE_PAGE = 20
MAX_PROJECT_MERGE_QUEUE_CONFLICTS = 100
MAX_PROJECT_MERGE_QUEUE_DOCUMENTS = 200


class ProjectMergeQueueService:
    """Page compact exact-head merge previews for project source branches."""

    def __init__(
        self,
        previews: MergePreviewService,
        statuses: ProjectAgentStatusService,
    ) -> None:
        self.previews = previews
        self.statuses = statuses
        self.workspace = previews.workspace

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
            self.statuses.__class__.__module__ and 500,
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

        project_id = self.workspace.project_id(project)
        members = self._catalog_members(project_id)
        target = next(
            (member for member in members if member["branch"] == target_branch),
            None,
        )
        if target is None:
            raise ValidationError(
                "INVALID_MERGE_QUEUE_TARGET",
                f"target branch {target_branch!r} is not in the project catalog",
            )
        sources = [member for member in members if member["branch"] != target_branch]
        effective_catalog_id = self.workspace.db.hash_value(
            {
                "format": PROJECT_MERGE_QUEUE_CATALOG_FORMAT,
                "project": project,
                "target": target,
                "sources": sources,
            }
        )
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
            "next_after_source": selected[-1]["branch"] if has_more and selected else None,
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
            "changed_documents_truncated": (
                len(changed_documents) > changed_document_limit
            ),
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
        rows = self.workspace.db.connection.execute(
            """SELECT name, head_revision_id
               FROM branches
               WHERE project_id = ?
               ORDER BY name
               LIMIT ?""",
            (project_id, MAX_AGENT_STATUS_BRANCH_CATALOG + 1),
        ).fetchall()
        if len(rows) > MAX_AGENT_STATUS_BRANCH_CATALOG:
            raise ValidationError(
                "MERGE_QUEUE_BRANCH_FANOUT_EXCEEDED",
                "project merge queue supports at most "
                f"{MAX_AGENT_STATUS_BRANCH_CATALOG} branches",
            )
        return [
            {
                "branch": str(row["name"]),
                "head_revision_id": str(row["head_revision_id"]),
            }
            for row in rows
        ]

    @staticmethod
    def _validate_limit(name: str, value: Any, maximum: int) -> None:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 1
            or value > maximum
        ):
            raise ValidationError(
                "INVALID_PROJECT_MERGE_QUEUE_LIMIT",
                f"{name} must be an integer between 1 and {maximum}",
            )

    @staticmethod
    def _validate_optional_id(name: str, value: Any) -> None:
        if value is not None and (not isinstance(value, str) or not value):
            raise ValidationError(
                "INVALID_MERGE_QUEUE_CURSOR",
                f"{name} must be a non-empty string or null",
            )
