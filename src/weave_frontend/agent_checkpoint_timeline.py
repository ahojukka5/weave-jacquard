"""Bounded checkpoint history and structured immutable progress comparison."""

from __future__ import annotations

import hashlib
from typing import Any

from .agent_checkpoint import AGENT_CHECKPOINT_OPERATION, AgentCheckpointRegistry
from .errors import NotFoundError, ValidationError

CHECKPOINT_TIMELINE_FORMAT = "weave-agent-checkpoint-timeline-v1"
CHECKPOINT_COMPARISON_FORMAT = "weave-agent-checkpoint-comparison-v1"
MAX_CHECKPOINT_PAGE = 50
MAX_CHECKPOINT_REVISION_SCAN = 500
MAX_TIMELINE_SUMMARY_PREVIEW_CHARS = 512


class AgentCheckpointTimelineService:
    """Read bounded first-parent handoff history and compare exact checkpoints."""

    def __init__(self, registry: AgentCheckpointRegistry) -> None:
        self.registry = registry
        self.workspace = registry.workspace

    def page(
        self,
        project: str,
        branch: str = "main",
        *,
        start_revision_id: str | None = None,
        limit: int = 20,
        revision_scan_limit: int = 200,
    ) -> dict[str, Any]:
        """Return newest-to-oldest checkpoints within bounded first-parent work."""

        self._validate_limit("limit", limit, MAX_CHECKPOINT_PAGE)
        self._validate_limit(
            "revision_scan_limit",
            revision_scan_limit,
            MAX_CHECKPOINT_REVISION_SCAN,
        )
        branch_head_revision_id = self.workspace.branch_head(project, branch)
        selected_revision_id = start_revision_id or branch_head_revision_id
        self._require_project_revision(project, selected_revision_id)

        entries: list[dict[str, Any]] = []
        current: str | None = selected_revision_id
        scanned_revision_count = 0
        while (
            current is not None
            and scanned_revision_count < revision_scan_limit
            and len(entries) < limit
        ):
            revision = self._revision(project, current)
            checkpoint = self._checkpoint_at_revision(project, current)
            scanned_revision_count += 1
            current = revision["parent1_id"]
            if checkpoint is not None:
                entries.append(self._timeline_entry(revision, checkpoint))

        result: dict[str, Any] = {
            "format": CHECKPOINT_TIMELINE_FORMAT,
            "project": project,
            "branch": branch,
            "branch_head_revision_id": branch_head_revision_id,
            "start_revision_id": selected_revision_id,
            "start_is_branch_head": selected_revision_id == branch_head_revision_id,
            "checkpoint_limit": limit,
            "revision_scan_limit": revision_scan_limit,
            "returned_checkpoint_count": len(entries),
            "scanned_revision_count": scanned_revision_count,
            "scan_limit_reached": (
                scanned_revision_count == revision_scan_limit and current is not None
            ),
            "checkpoint_limit_reached": len(entries) == limit and current is not None,
            "has_more": current is not None,
            "next_revision_id": current,
            "checkpoints": entries,
            "ordering": "newest-to-oldest first-parent checkpoint revisions",
        }
        result["page_id"] = self.workspace.db.hash_value(result)
        return result

    def compare(
        self,
        project: str,
        base_checkpoint_revision_id: str,
        target_checkpoint_revision_id: str,
    ) -> dict[str, Any]:
        """Compare two exact project-owned checkpoint revisions without inference."""

        base_revision = self._revision(project, base_checkpoint_revision_id)
        target_revision = self._revision(project, target_checkpoint_revision_id)
        base = self._require_checkpoint_at_revision(
            project,
            base_checkpoint_revision_id,
        )
        target = self._require_checkpoint_at_revision(
            project,
            target_checkpoint_revision_id,
        )
        base_checkpoint = base["checkpoint"]
        target_checkpoint = target["checkpoint"]

        list_deltas = {
            field: self._list_delta(base_checkpoint[field], target_checkpoint[field])
            for field in (
                "completed",
                "next_steps",
                "open_questions",
                "validation",
            )
        }
        result: dict[str, Any] = {
            "format": CHECKPOINT_COMPARISON_FORMAT,
            "project": project,
            "base": self._comparison_endpoint(base_revision, base),
            "target": self._comparison_endpoint(target_revision, target),
            "program_state_changed": (
                base_revision["root_hash"] != target_revision["root_hash"]
            ),
            "status": {
                "base": base_checkpoint["status"],
                "target": target_checkpoint["status"],
                "changed": base_checkpoint["status"] != target_checkpoint["status"],
            },
            "objective": {
                "base": base_checkpoint["objective"],
                "target": target_checkpoint["objective"],
                "changed": (
                    base_checkpoint["objective"] != target_checkpoint["objective"]
                ),
            },
            "summary": {
                "base_sha256": self._text_hash(base_checkpoint["summary"]),
                "target_sha256": self._text_hash(target_checkpoint["summary"]),
                "changed": base_checkpoint["summary"] != target_checkpoint["summary"],
                "base_preview": self._preview(base_checkpoint["summary"]),
                "target_preview": self._preview(target_checkpoint["summary"]),
            },
            "list_deltas": list_deltas,
            "changed": any(
                (
                    base_checkpoint["status"] != target_checkpoint["status"],
                    base_checkpoint["objective"] != target_checkpoint["objective"],
                    base_checkpoint["summary"] != target_checkpoint["summary"],
                    any(delta["changed"] for delta in list_deltas.values()),
                    base_revision["root_hash"] != target_revision["root_hash"],
                )
            ),
            "interpretation_note": (
                "added and removed items are structural differences only; removal does "
                "not prove completion, resolution, or invalidation"
            ),
            "ordering_note": (
                "the comparison does not imply that base is an ancestor of target"
            ),
        }
        result["comparison_id"] = self.workspace.db.hash_value(result)
        return result

    def _checkpoint_at_revision(
        self,
        project: str,
        revision_id: str,
    ) -> dict[str, Any] | None:
        row = self.workspace.db.connection.execute(
            """SELECT payload_json
               FROM operations
               WHERE revision_id = ? AND operation_kind = ?
               ORDER BY sequence_number DESC
               LIMIT 1""",
            (revision_id, AGENT_CHECKPOINT_OPERATION),
        ).fetchone()
        if row is None:
            return None
        payload = self.registry._operation_payload(str(row["payload_json"]))
        checkpoint_id = payload["document_id"]
        checkpoint = self.registry._read_document(project, checkpoint_id)
        checkpoint_hash = self.workspace.db.hash_value(checkpoint)
        if payload["checkpoint_hash"] != checkpoint_hash:
            raise ValidationError(
                "INVALID_AGENT_CHECKPOINT",
                "agent checkpoint operation hash does not match its document",
            )
        return {
            "checkpoint_id": checkpoint_id,
            "checkpoint_hash": checkpoint_hash,
            "checkpoint": checkpoint,
        }

    def _require_checkpoint_at_revision(
        self,
        project: str,
        revision_id: str,
    ) -> dict[str, Any]:
        checkpoint = self._checkpoint_at_revision(project, revision_id)
        if checkpoint is None:
            raise ValidationError(
                "CHECKPOINT_REVISION_REQUIRED",
                f"revision {revision_id!r} did not publish an agent checkpoint",
            )
        return checkpoint

    def _revision(self, project: str, revision_id: str) -> dict[str, Any]:
        row = self.workspace.db.connection.execute(
            """SELECT r.id, r.parent1_id, r.parent2_id, r.message, r.author,
                      r.root_hash, r.created_at
               FROM revisions r
               JOIN projects p ON p.id = r.project_id
               WHERE r.id = ? AND p.name = ?""",
            (revision_id, project),
        ).fetchone()
        if row is None:
            raise NotFoundError(
                f"revision {revision_id!r} does not belong to project {project!r}"
            )
        return {
            "id": str(row["id"]),
            "parent1_id": (
                str(row["parent1_id"]) if row["parent1_id"] is not None else None
            ),
            "parent2_id": (
                str(row["parent2_id"]) if row["parent2_id"] is not None else None
            ),
            "message": str(row["message"]),
            "author": str(row["author"]),
            "root_hash": str(row["root_hash"]),
            "created_at": str(row["created_at"]),
        }

    def _require_project_revision(self, project: str, revision_id: str) -> None:
        self._revision(project, revision_id)

    @staticmethod
    def _timeline_entry(
        revision: dict[str, Any],
        checkpoint: dict[str, Any],
    ) -> dict[str, Any]:
        value = checkpoint["checkpoint"]
        summary = value["summary"]
        preview = summary[:MAX_TIMELINE_SUMMARY_PREVIEW_CHARS]
        return {
            "checkpoint_revision_id": revision["id"],
            "checkpoint_id": checkpoint["checkpoint_id"],
            "checkpoint_hash": checkpoint["checkpoint_hash"],
            "created_at": revision["created_at"],
            "author": revision["author"],
            "root_hash": revision["root_hash"],
            "status": value["status"],
            "objective": value["objective"],
            "summary_sha256": AgentCheckpointTimelineService._text_hash(summary),
            "summary_preview": preview,
            "summary_truncated": len(preview) < len(summary),
            "completed_count": len(value["completed"]),
            "next_step_count": len(value["next_steps"]),
            "open_question_count": len(value["open_questions"]),
            "validation_count": len(value["validation"]),
            "resume": {
                "tool": "branch_resume_snapshot",
                "arguments": {
                    "revision_id": revision["id"],
                },
            },
        }

    @staticmethod
    def _comparison_endpoint(
        revision: dict[str, Any],
        checkpoint: dict[str, Any],
    ) -> dict[str, Any]:
        value = checkpoint["checkpoint"]
        return {
            "checkpoint_revision_id": revision["id"],
            "checkpoint_id": checkpoint["checkpoint_id"],
            "checkpoint_hash": checkpoint["checkpoint_hash"],
            "root_hash": revision["root_hash"],
            "created_at": revision["created_at"],
            "author": revision["author"],
            "status": value["status"],
            "objective": value["objective"],
        }

    @staticmethod
    def _list_delta(base: list[str], target: list[str]) -> dict[str, Any]:
        base_set = set(base)
        target_set = set(target)
        added = [item for item in target if item not in base_set]
        removed = [item for item in base if item not in target_set]
        return {
            "base_count": len(base),
            "target_count": len(target),
            "added": added,
            "removed": removed,
            "changed": bool(added or removed),
        }

    @staticmethod
    def _preview(value: str) -> dict[str, Any]:
        preview = value[:MAX_TIMELINE_SUMMARY_PREVIEW_CHARS]
        return {
            "text": preview,
            "truncated": len(preview) < len(value),
            "characters": len(value),
        }

    @staticmethod
    def _text_hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_limit(name: str, value: Any, maximum: int) -> None:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 1
            or value > maximum
        ):
            raise ValidationError(
                "INVALID_CHECKPOINT_TIMELINE_LIMIT",
                f"{name} must be an integer between 1 and {maximum}",
            )
