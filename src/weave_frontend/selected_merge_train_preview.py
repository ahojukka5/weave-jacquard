"""Order-aware in-memory merge-train previews for explicit source selections."""

from __future__ import annotations

from typing import Any

from .errors import ConflictError, ValidationError
from .project_merge_queue import (
    MAX_PROJECT_MERGE_QUEUE_CONFLICTS,
    MAX_PROJECT_MERGE_QUEUE_DOCUMENTS,
    ProjectMergeQueueService,
)

SELECTED_MERGE_TRAIN_FORMAT = "weave-selected-merge-train-preview-v1"
MAX_SELECTED_MERGE_TRAIN_SOURCES = 10


class SelectedMergeTrainPreviewService:
    """Simulate ordered source merges into one virtual target without publication."""

    def __init__(self, queues: ProjectMergeQueueService) -> None:
        self.queues = queues
        self.catalogs = queues.catalogs
        self.previews = queues.previews
        self.workspace = queues.workspace

    def preview(
        self,
        project: str,
        target_branch: str,
        sources: list[str],
        catalog_id: str,
        *,
        conflict_limit: int = 20,
        changed_document_limit: int = 50,
    ) -> dict[str, Any]:
        """Return deterministic ordered virtual merge evidence for exact heads."""

        selected = self._validate_sources(sources)
        self._validate_id(catalog_id)
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

        target, source_members, effective_catalog_id = self._catalog(
            project,
            target_branch,
        )
        if catalog_id != effective_catalog_id:
            raise ValidationError(
                "STALE_SELECTED_MERGE_TRAIN_CATALOG",
                "project branch heads changed since the selected merge-train catalog",
            )
        by_source = {member["branch"]: member for member in source_members}
        missing = [source for source in selected if source not in by_source]
        if missing:
            raise ValidationError(
                "INVALID_SELECTED_MERGE_TRAIN_SOURCE",
                "selected sources are not source branches in the catalog: "
                + ", ".join(missing),
            )

        target_head = target["head_revision_id"]
        current_state = self.workspace._state_at_revision(target_head)
        initial_root_hash = self.workspace.db.hash_value(current_state)
        current_root_hash = initial_root_hash
        steps: list[dict[str, Any]] = []
        conflict_index: int | None = None

        for index, source_name in enumerate(selected):
            source = by_source[source_name]
            step = self._step(
                project,
                target,
                source,
                index=index,
                virtual_target_state=current_state,
                virtual_target_root_hash=current_root_hash,
                conflict_limit=conflict_limit,
                changed_document_limit=changed_document_limit,
            )
            steps.append(step["public"])
            if not step["public"]["train_step_mergeable"]:
                conflict_index = index
                break
            current_state = step["merged_state"]
            current_root_hash = step["public"]["virtual_target_root_after"]

        _, _, final_catalog_id = self._catalog(project, target_branch)
        if final_catalog_id != effective_catalog_id:
            raise ValidationError(
                "STALE_SELECTED_MERGE_TRAIN_CATALOG",
                "project branch heads changed while simulating the selected merge train",
            )

        applied_count = sum(step["train_step_mergeable"] for step in steps)
        simulated_count = len(steps)
        remaining = selected[simulated_count:]
        complete = conflict_index is None and simulated_count == len(selected)
        first_step = steps[0] if steps else None
        result: dict[str, Any] = {
            "format": SELECTED_MERGE_TRAIN_FORMAT,
            "project": project,
            "target_branch": target_branch,
            "target_head_revision_id": target_head,
            "catalog_id": effective_catalog_id,
            "selected_sources": selected,
            "selected_source_count": len(selected),
            "conflict_limit": conflict_limit,
            "changed_document_limit": changed_document_limit,
            "initial_target_root_hash": initial_root_hash,
            "final_virtual_target_root_hash": current_root_hash,
            "simulated_source_count": simulated_count,
            "applied_source_count": applied_count,
            "train_complete": complete,
            "conflict_step_index": conflict_index,
            "remaining_sources_not_simulated": remaining,
            "steps": steps,
            "first_publication_candidate": (
                {
                    "tool": "branch_merge_preflight",
                    "arguments": {
                        "project": project,
                        "target_branch": target_branch,
                        "source_branch": first_step["source_branch"],
                        "preview_id": first_step["original_preview_id"],
                    },
                }
                if first_step is not None and first_step["train_step_mergeable"]
                else None
            ),
            "simulation_note": (
                "the virtual train is structural and in-memory only; no compiler, preflight, "
                "or merge publication ran"
            ),
            "refresh_note": (
                "after publishing any real step, obtain a fresh catalog and preflight before "
                "publishing the next source because the target head has changed"
            ),
            "ordering_note": (
                "source order is explicit caller input and can change train conflicts or "
                "redundancy; it does not itself express priority, quality, age, or readiness"
            ),
        }
        result["train_id"] = self.workspace.db.hash_value(result)
        return result

    def _step(
        self,
        project: str,
        target: dict[str, str],
        source: dict[str, str],
        *,
        index: int,
        virtual_target_state: dict[str, dict[str, Any]],
        virtual_target_root_hash: str,
        conflict_limit: int,
        changed_document_limit: int,
    ) -> dict[str, Any]:
        source_name = source["branch"]
        source_head = source["head_revision_id"]
        original = self.previews.preview(
            project,
            target["branch"],
            source_name,
        )
        if (
            original["target_head_revision_id"] != target["head_revision_id"]
            or original["source_head_revision_id"] != source_head
        ):
            raise ValidationError(
                "STALE_SELECTED_MERGE_TRAIN_CATALOG",
                "a target or source branch advanced before train simulation",
            )

        base_revision = self.workspace._common_ancestor(
            target["head_revision_id"],
            source_head,
        )
        base_state = self.workspace._state_at_revision(base_revision)
        source_state = self.workspace._state_at_revision(source_head)
        try:
            merged_state, changed = self.workspace._merge_states(
                base_state,
                virtual_target_state,
                source_state,
            )
            self.workspace._validate_state(merged_state)
        except ConflictError as exc:
            conflicts = list(exc.conflicts)
            relation = (
                "consistent_conflict"
                if not original["mergeable"]
                else "order_introduced_conflict"
            )
            return {
                "public": {
                    "step_index": index,
                    "source_branch": source_name,
                    "source_head_revision_id": source_head,
                    "base_revision_id": base_revision,
                    "virtual_target_root_before": virtual_target_root_hash,
                    "virtual_target_root_after": None,
                    "original_preview_id": original["preview_id"],
                    "original_preview_mergeable": original["mergeable"],
                    "train_step_mergeable": False,
                    "relation_to_original_preview": relation,
                    "conflict_count": len(conflicts),
                    "conflicts": conflicts[:conflict_limit],
                    "conflicts_truncated": len(conflicts) > conflict_limit,
                    "changed_document_count": 0,
                    "changed_documents": [],
                    "changed_documents_truncated": False,
                    "no_changes": False,
                    "publication_requires_refresh_after_prior_step": index > 0,
                },
                "merged_state": None,
            }

        changed_documents = sorted(changed)
        merged_root_hash = self.workspace.db.hash_value(merged_state)
        relation = (
            "consistent_clean"
            if original["mergeable"]
            else "order_removed_conflict"
        )
        return {
            "public": {
                "step_index": index,
                "source_branch": source_name,
                "source_head_revision_id": source_head,
                "base_revision_id": base_revision,
                "virtual_target_root_before": virtual_target_root_hash,
                "virtual_target_root_after": merged_root_hash,
                "original_preview_id": original["preview_id"],
                "original_preview_mergeable": original["mergeable"],
                "train_step_mergeable": True,
                "relation_to_original_preview": relation,
                "conflict_count": 0,
                "conflicts": [],
                "conflicts_truncated": False,
                "changed_document_count": len(changed_documents),
                "changed_documents": changed_documents[:changed_document_limit],
                "changed_documents_truncated": (
                    len(changed_documents) > changed_document_limit
                ),
                "no_changes": not changed_documents,
                "publication_requires_refresh_after_prior_step": index > 0,
            },
            "merged_state": merged_state,
        }

    def _catalog(
        self,
        project: str,
        target_branch: str,
    ) -> tuple[dict[str, str], list[dict[str, str]], str]:
        catalog = self.catalogs.capture(
            project,
            target_branch,
            invalid_target_code="INVALID_SELECTED_MERGE_TRAIN_TARGET",
        )
        return catalog["target"], catalog["sources"], catalog["catalog_id"]

    @staticmethod
    def _validate_sources(value: Any) -> list[str]:
        if not isinstance(value, list) or not value:
            raise ValidationError(
                "INVALID_SELECTED_MERGE_TRAIN_SOURCES",
                "sources must be a non-empty list",
            )
        if len(value) > MAX_SELECTED_MERGE_TRAIN_SOURCES:
            raise ValidationError(
                "INVALID_SELECTED_MERGE_TRAIN_SOURCES",
                "sources may contain at most "
                f"{MAX_SELECTED_MERGE_TRAIN_SOURCES} branches",
            )
        result: list[str] = []
        for source in value:
            if not isinstance(source, str) or not source:
                raise ValidationError(
                    "INVALID_SELECTED_MERGE_TRAIN_SOURCES",
                    "every source must be a non-empty string",
                )
            if source in result:
                raise ValidationError(
                    "INVALID_SELECTED_MERGE_TRAIN_SOURCES",
                    f"duplicate selected source {source!r}",
                )
            result.append(source)
        return result

    @staticmethod
    def _validate_id(value: Any) -> None:
        if not isinstance(value, str) or not value:
            raise ValidationError(
                "INVALID_SELECTED_MERGE_TRAIN_CATALOG",
                "catalog_id must be a non-empty string",
            )

    @staticmethod
    def _validate_limit(name: str, value: Any, maximum: int) -> None:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 1
            or value > maximum
        ):
            raise ValidationError(
                "INVALID_SELECTED_MERGE_TRAIN_LIMIT",
                f"{name} must be an integer between 1 and {maximum}",
            )
