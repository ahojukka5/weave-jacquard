"""Compiler-backed preflight batches for explicit exact-catalog source selections."""

from __future__ import annotations

from typing import Any

from .errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
    WeaveFrontendError,
)
from .merge_preflight import MergePreflightService
from .merge_validation_set import MAX_AFFECTED_TARGET_VALIDATIONS
from .project_merge_queue import ProjectMergeQueueService

SELECTED_MERGE_PREFLIGHT_BATCH_FORMAT = "weave-selected-merge-preflight-batch-v1"
MAX_SELECTED_MERGE_PREFLIGHT_SOURCES = 5
MAX_SELECTED_MERGE_PREFLIGHT_DOCUMENTS = 200


class SelectedMergePreflightBatchService:
    """Run normal preflight only for caller-selected exact-catalog sources."""

    def __init__(
        self,
        queues: ProjectMergeQueueService,
        preflights: MergePreflightService,
    ) -> None:
        self.queues = queues
        self.catalogs = queues.catalogs
        self.preflights = preflights
        self.workspace = queues.workspace

    def run(
        self,
        project: str,
        target_branch: str,
        sources: list[str],
        catalog_id: str,
        *,
        allow_uncovered_sources: list[str] | None = None,
        validation_result_limit: int = 20,
        document_limit: int = 100,
    ) -> dict[str, Any]:
        """Return independent bounded preflight evidence for explicit sources."""

        selected = self._validate_sources(sources)
        allowed = self._validate_allowed(allow_uncovered_sources, selected)
        self._validate_id("catalog_id", catalog_id)
        self._validate_limit(
            "validation_result_limit",
            validation_result_limit,
            MAX_AFFECTED_TARGET_VALIDATIONS,
        )
        self._validate_limit(
            "document_limit",
            document_limit,
            MAX_SELECTED_MERGE_PREFLIGHT_DOCUMENTS,
        )

        target, source_members, effective_catalog_id = self._catalog(
            project,
            target_branch,
        )
        if catalog_id != effective_catalog_id:
            raise ValidationError(
                "STALE_SELECTED_PREFLIGHT_CATALOG",
                "project branch heads changed since the selected preflight catalog",
            )
        by_source = {member["branch"]: member for member in source_members}
        missing = [source for source in selected if source not in by_source]
        if missing:
            raise ValidationError(
                "INVALID_SELECTED_PREFLIGHT_SOURCE",
                "selected sources are not source branches in the catalog: " + ", ".join(missing),
            )

        entries = [
            self._run_source(
                project,
                target,
                by_source[source],
                allow_uncovered_documents=source in allowed,
                validation_result_limit=validation_result_limit,
                document_limit=document_limit,
            )
            for source in selected
        ]
        _, _, final_catalog_id = self._catalog(project, target_branch)
        if final_catalog_id != effective_catalog_id:
            raise ValidationError(
                "STALE_SELECTED_PREFLIGHT_CATALOG",
                "project branch heads changed while running the selected preflight batch",
            )

        completed = [entry for entry in entries if entry["status"] == "completed"]
        errors = [entry for entry in entries if entry["status"] == "error"]
        ready = [entry for entry in completed if entry["ready_for_publication"]]
        result: dict[str, Any] = {
            "format": SELECTED_MERGE_PREFLIGHT_BATCH_FORMAT,
            "project": project,
            "target_branch": target_branch,
            "target_head_revision_id": target["head_revision_id"],
            "catalog_id": effective_catalog_id,
            "selected_sources": selected,
            "allow_uncovered_sources": sorted(allowed),
            "validation_result_limit": validation_result_limit,
            "document_limit": document_limit,
            "selected_source_count": len(selected),
            "completed_source_count": len(completed),
            "error_source_count": len(errors),
            "ready_source_count": len(ready),
            "not_ready_source_count": len(completed) - len(ready),
            "sources": entries,
            "execution_note": (
                "compiler-backed preflight ran only for the explicit selected sources in "
                "caller order; no merge was published"
            ),
            "ordering_note": (
                "selected source order is caller input and does not itself express priority, "
                "quality, or readiness"
            ),
            "publication_note": (
                "ready_for_publication is exact preflight evidence only; publication must "
                "still replay branch_merge with the returned guarded arguments"
            ),
        }
        result["batch_id"] = self.workspace.db.hash_value(result)
        return result

    def _run_source(
        self,
        project: str,
        target: dict[str, str],
        source: dict[str, str],
        *,
        allow_uncovered_documents: bool,
        validation_result_limit: int,
        document_limit: int,
    ) -> dict[str, Any]:
        preview = self.queues.previews.preview(
            project,
            target["branch"],
            source["branch"],
        )
        self._require_exact_preview(preview, target, source)
        replay = {
            "tool": "branch_merge_preflight",
            "arguments": {
                "project": project,
                "target_branch": target["branch"],
                "source_branch": source["branch"],
                "preview_id": preview["preview_id"],
                "allow_uncovered_documents": allow_uncovered_documents,
            },
        }
        try:
            preflight = self.preflights.run(
                project,
                target["branch"],
                source["branch"],
                preview_id=str(preview["preview_id"]),
                allow_uncovered_documents=allow_uncovered_documents,
            )
        except ValidationError as exc:
            if exc.code == "STALE_MERGE_PREVIEW":
                raise ValidationError(
                    "STALE_SELECTED_PREFLIGHT_CATALOG",
                    "a selected source or target advanced during preflight",
                ) from exc
            return self._error_entry(
                source,
                preview,
                allow_uncovered_documents,
                replay,
                exc.as_dict(),
            )
        except ConflictError as exc:
            return self._error_entry(
                source,
                preview,
                allow_uncovered_documents,
                replay,
                {
                    "code": "MERGE_CONFLICT",
                    "message": str(exc),
                    "conflicts": list(exc.conflicts),
                },
            )
        except NotFoundError as exc:
            return self._error_entry(
                source,
                preview,
                allow_uncovered_documents,
                replay,
                {"code": "NOT_FOUND", "message": str(exc)},
            )
        except WeaveFrontendError as exc:
            return self._error_entry(
                source,
                preview,
                allow_uncovered_documents,
                replay,
                {"code": "PREFLIGHT_ERROR", "message": str(exc)},
            )

        if (
            preflight["target_head_revision_id"] != target["head_revision_id"]
            or preflight["source_head_revision_id"] != source["head_revision_id"]
            or preflight["preview_id"] != preview["preview_id"]
        ):
            raise ValidationError(
                "STALE_SELECTED_PREFLIGHT_CATALOG",
                "preflight evidence did not match the exact selected catalog heads",
            )
        impact = preflight["impact"]
        validation = preflight["validation_set"]
        target_validations = list(validation["target_validations"])
        compact_validations = [
            {
                key: record[key]
                for key in (
                    "target",
                    "validation_id",
                    "available",
                    "valid",
                    "returncode",
                    "timed_out",
                    "diagnostic",
                    "compiler_sha256",
                    "wir_sha256",
                    "wir_bytes",
                )
            }
            for record in target_validations[:validation_result_limit]
        ]
        return {
            "source_branch": source["branch"],
            "source_head_revision_id": source["head_revision_id"],
            "preview_id": preview["preview_id"],
            "status": "completed",
            "error": None,
            "allow_uncovered_documents": allow_uncovered_documents,
            "preflight_id": preflight["preflight_id"],
            "base_revision_id": preflight["base_revision_id"],
            "merged_root_hash": preflight["merged_root_hash"],
            "ready_for_publication": preflight["ready_for_publication"],
            "changed_program_document_count": len(impact["changed_program_documents"]),
            "changed_program_documents": impact["changed_program_documents"][:document_limit],
            "changed_program_documents_truncated": (
                len(impact["changed_program_documents"]) > document_limit
            ),
            "uncovered_changed_document_count": len(impact["uncovered_changed_documents"]),
            "uncovered_changed_documents": impact["uncovered_changed_documents"][:document_limit],
            "uncovered_changed_documents_truncated": (
                len(impact["uncovered_changed_documents"]) > document_limit
            ),
            "impact_affected_target_count": impact["total_affected_target_count"],
            "impact_targets_truncated": preflight["impact_targets_truncated"],
            "coverage_passed": validation["coverage_passed"],
            "affected_surviving_target_count": validation["affected_surviving_target_count"],
            "validated_target_count": validation["validated_target_count"],
            "passed_target_count": validation["passed_target_count"],
            "failed_target_count": validation["failed_target_count"],
            "unavailable_target_count": validation["unavailable_target_count"],
            "passed_targets": validation["passed_targets"][:validation_result_limit],
            "failed_targets": validation["failed_targets"][:validation_result_limit],
            "unavailable_targets": validation["unavailable_targets"][:validation_result_limit],
            "returned_target_validation_count": len(compact_validations),
            "target_validations_truncated": (len(target_validations) > validation_result_limit),
            "target_validations": compact_validations,
            "target_merge_policy": preflight.get("target_merge_policy"),
            "source_merge_policy": preflight.get("source_merge_policy"),
            "source_policy_ignored": preflight.get("source_policy_ignored", False),
            "publication_tool": preflight["publication_tool"],
            "publication_arguments": preflight["publication_arguments"],
            "full_preflight": replay,
        }

    @staticmethod
    def _error_entry(
        source: dict[str, str],
        preview: dict[str, Any],
        allow_uncovered_documents: bool,
        replay: dict[str, Any],
        error: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "source_branch": source["branch"],
            "source_head_revision_id": source["head_revision_id"],
            "preview_id": preview["preview_id"],
            "status": "error",
            "error": error,
            "allow_uncovered_documents": allow_uncovered_documents,
            "preflight_id": None,
            "ready_for_publication": False,
            "full_preflight": replay,
        }

    def _catalog(
        self,
        project: str,
        target_branch: str,
    ) -> tuple[dict[str, str], list[dict[str, str]], str]:
        catalog = self.catalogs.capture(
            project,
            target_branch,
            invalid_target_code="INVALID_SELECTED_PREFLIGHT_TARGET",
        )
        return catalog["target"], catalog["sources"], catalog["catalog_id"]

    @staticmethod
    def _require_exact_preview(
        preview: dict[str, Any],
        target: dict[str, str],
        source: dict[str, str],
    ) -> None:
        if (
            preview["target_head_revision_id"] != target["head_revision_id"]
            or preview["source_head_revision_id"] != source["head_revision_id"]
        ):
            raise ValidationError(
                "STALE_SELECTED_PREFLIGHT_CATALOG",
                "a selected source or target advanced before preflight",
            )

    @staticmethod
    def _validate_sources(sources: Any) -> list[str]:
        if not isinstance(sources, list) or not sources:
            raise ValidationError(
                "INVALID_SELECTED_PREFLIGHT_SOURCES",
                "sources must be a non-empty list",
            )
        if len(sources) > MAX_SELECTED_MERGE_PREFLIGHT_SOURCES:
            raise ValidationError(
                "INVALID_SELECTED_PREFLIGHT_SOURCES",
                f"sources may contain at most {MAX_SELECTED_MERGE_PREFLIGHT_SOURCES} branches",
            )
        result: list[str] = []
        for source in sources:
            if not isinstance(source, str) or not source:
                raise ValidationError(
                    "INVALID_SELECTED_PREFLIGHT_SOURCES",
                    "every source must be a non-empty string",
                )
            if source in result:
                raise ValidationError(
                    "INVALID_SELECTED_PREFLIGHT_SOURCES",
                    f"duplicate selected source {source!r}",
                )
            result.append(source)
        return result

    @staticmethod
    def _validate_allowed(value: Any, sources: list[str]) -> set[str]:
        if value is None:
            return set()
        if not isinstance(value, list):
            raise ValidationError(
                "INVALID_SELECTED_PREFLIGHT_OVERRIDES",
                "allow_uncovered_sources must be a list or null",
            )
        allowed: set[str] = set()
        for source in value:
            if not isinstance(source, str) or not source:
                raise ValidationError(
                    "INVALID_SELECTED_PREFLIGHT_OVERRIDES",
                    "every override source must be a non-empty string",
                )
            if source in allowed:
                raise ValidationError(
                    "INVALID_SELECTED_PREFLIGHT_OVERRIDES",
                    f"duplicate uncovered override source {source!r}",
                )
            if source not in sources:
                raise ValidationError(
                    "INVALID_SELECTED_PREFLIGHT_OVERRIDES",
                    f"override source {source!r} is not selected",
                )
            allowed.add(source)
        return allowed

    @staticmethod
    def _validate_id(name: str, value: Any) -> None:
        if not isinstance(value, str) or not value:
            raise ValidationError(
                "INVALID_SELECTED_PREFLIGHT_CATALOG",
                f"{name} must be a non-empty string",
            )

    @staticmethod
    def _validate_limit(name: str, value: Any, maximum: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > maximum:
            raise ValidationError(
                "INVALID_SELECTED_PREFLIGHT_LIMIT",
                f"{name} must be an integer between 1 and {maximum}",
            )
