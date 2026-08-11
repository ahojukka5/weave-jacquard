"""Revisioned structured handoff checkpoints for coding agents."""

from __future__ import annotations

import json
from typing import Any

from ..errors import NotFoundError, ValidationError

AGENT_CHECKPOINT_FORMAT = "weave-agent-checkpoint-v1"
AGENT_CHECKPOINT_TITLE = "Jacquard agent checkpoint"
AGENT_CHECKPOINT_OPERATION = "create_agent_checkpoint"
AGENT_CHECKPOINT_STATUSES = {
    "in_progress",
    "blocked",
    "ready_for_review",
    "complete",
}
MAX_CHECKPOINT_OBJECTIVE_CHARS = 2_000
MAX_CHECKPOINT_SUMMARY_CHARS = 16_000
MAX_CHECKPOINT_ITEMS = 64
MAX_CHECKPOINT_ITEM_CHARS = 2_000


class AgentCheckpointRegistry:
    """Publish and resolve structured checkpoints on immutable branch history."""

    def __init__(self, workspace: Any) -> None:
        self.workspace = workspace

    def create(
        self,
        project: str,
        branch: str = "main",
        *,
        objective: str,
        summary: str,
        status: str = "in_progress",
        completed: list[str] | None = None,
        next_steps: list[str] | None = None,
        open_questions: list[str] | None = None,
        validation: list[str] | None = None,
        expected_revision_id: str | None = None,
        author: str = "agent",
    ) -> dict[str, Any]:
        """Publish one structured checkpoint without changing program state."""

        checkpoint = self._normalize(
            objective=objective,
            summary=summary,
            status=status,
            completed=completed,
            next_steps=next_steps,
            open_questions=open_questions,
            validation=validation,
        )
        body = self.workspace.db.canonical_json(checkpoint)
        checkpoint_hash = self.workspace.db.hash_value(checkpoint)
        base_revision_id, state = self.workspace._state_for_write(
            project,
            branch,
            expected_revision_id=expected_revision_id,
        )
        revision_id, checkpoint_id = self.workspace._commit_content_document(
            project,
            branch,
            base_revision_id,
            state,
            scope_kind="project",
            scope_name=project,
            title=AGENT_CHECKPOINT_TITLE,
            body=body,
            message=f"publish agent checkpoint {checkpoint['status']}",
            author=author,
            operation_kind=AGENT_CHECKPOINT_OPERATION,
            operation_target=branch,
            operation_payload={
                "format": AGENT_CHECKPOINT_FORMAT,
                "checkpoint_hash": checkpoint_hash,
                "status": checkpoint["status"],
                "objective": checkpoint["objective"],
            },
        )
        result = self._result(
            checkpoint,
            configured=True,
            project=project,
            branch=branch,
            selected_revision_id=revision_id,
            branch_head_revision_id=revision_id,
            checkpoint_revision_id=revision_id,
            checkpoint_id=checkpoint_id,
            checkpoint_hash=checkpoint_hash,
        )
        result["base_revision_id"] = base_revision_id
        return result

    def get(
        self,
        project: str,
        branch: str = "main",
        *,
        revision_id: str | None = None,
    ) -> dict[str, Any]:
        """Resolve the newest checkpoint on one selected revision's first-parent history."""

        branch_head_revision_id = self.workspace.branch_head(project, branch)
        selected_revision_id = revision_id or branch_head_revision_id
        self._require_project_revision(project, selected_revision_id)

        current: str | None = selected_revision_id
        while current is not None:
            row = self.workspace.db.connection.execute(
                """SELECT payload_json
                   FROM operations
                   WHERE revision_id = ? AND operation_kind = ?
                   ORDER BY sequence_number DESC
                   LIMIT 1""",
                (current, AGENT_CHECKPOINT_OPERATION),
            ).fetchone()
            if row is not None:
                payload = self._operation_payload(str(row["payload_json"]))
                checkpoint_id = payload["document_id"]
                checkpoint = self._read_document(project, checkpoint_id)
                checkpoint_hash = self.workspace.db.hash_value(checkpoint)
                if payload["checkpoint_hash"] != checkpoint_hash:
                    raise ValidationError(
                        "INVALID_AGENT_CHECKPOINT",
                        "agent checkpoint operation hash does not match its document",
                    )
                return self._result(
                    checkpoint,
                    configured=True,
                    project=project,
                    branch=branch,
                    selected_revision_id=selected_revision_id,
                    branch_head_revision_id=branch_head_revision_id,
                    checkpoint_revision_id=current,
                    checkpoint_id=checkpoint_id,
                    checkpoint_hash=checkpoint_hash,
                )
            parent = self.workspace.db.connection.execute(
                "SELECT parent1_id FROM revisions WHERE id = ?",
                (current,),
            ).fetchone()
            current = str(parent["parent1_id"]) if parent and parent["parent1_id"] else None

        return self._result(
            None,
            configured=False,
            project=project,
            branch=branch,
            selected_revision_id=selected_revision_id,
            branch_head_revision_id=branch_head_revision_id,
            checkpoint_revision_id=None,
            checkpoint_id=None,
            checkpoint_hash=None,
        )

    def _read_document(self, project: str, checkpoint_id: str) -> dict[str, Any]:
        row = self.workspace.db.connection.execute(
            """SELECT scope_kind, scope_name, title, body
               FROM documents WHERE id = ?""",
            (checkpoint_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"agent checkpoint document {checkpoint_id!r} not found")
        if (
            row["scope_kind"] != "project"
            or row["scope_name"] != project
            or row["title"] != AGENT_CHECKPOINT_TITLE
        ):
            raise ValidationError(
                "INVALID_AGENT_CHECKPOINT",
                "agent checkpoint document has the wrong project scope or title",
            )
        try:
            raw = json.loads(str(row["body"]))
        except json.JSONDecodeError as exc:
            raise ValidationError(
                "INVALID_AGENT_CHECKPOINT",
                "agent checkpoint document is not valid JSON",
            ) from exc
        if not isinstance(raw, dict):
            raise ValidationError(
                "INVALID_AGENT_CHECKPOINT",
                "agent checkpoint document must contain a JSON object",
            )
        return self._normalize(
            objective=raw.get("objective"),
            summary=raw.get("summary"),
            status=raw.get("status"),
            completed=raw.get("completed"),
            next_steps=raw.get("next_steps"),
            open_questions=raw.get("open_questions"),
            validation=raw.get("validation"),
            expected_format=raw.get("format"),
        )

    @staticmethod
    def _operation_payload(payload_json: str) -> dict[str, str]:
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError as exc:
            raise ValidationError(
                "INVALID_AGENT_CHECKPOINT",
                "agent checkpoint operation is not valid JSON",
            ) from exc
        if not isinstance(payload, dict):
            raise ValidationError(
                "INVALID_AGENT_CHECKPOINT",
                "agent checkpoint operation must contain a JSON object",
            )
        if payload.get("format") != AGENT_CHECKPOINT_FORMAT:
            raise ValidationError(
                "INVALID_AGENT_CHECKPOINT",
                f"agent checkpoint format must be {AGENT_CHECKPOINT_FORMAT!r}",
            )
        result: dict[str, str] = {}
        for name in ("document_id", "checkpoint_hash"):
            value = payload.get(name)
            if not isinstance(value, str) or not value:
                raise ValidationError(
                    "INVALID_AGENT_CHECKPOINT",
                    f"agent checkpoint operation requires non-empty {name}",
                )
            result[name] = value
        return result

    def _require_project_revision(self, project: str, revision_id: str) -> None:
        row = self.workspace.db.connection.execute(
            """SELECT 1
               FROM revisions r
               JOIN projects p ON p.id = r.project_id
               WHERE r.id = ? AND p.name = ?""",
            (revision_id, project),
        ).fetchone()
        if row is None:
            raise NotFoundError(
                f"revision {revision_id!r} does not belong to project {project!r}"
            )

    @classmethod
    def _normalize(
        cls,
        *,
        objective: Any,
        summary: Any,
        status: Any,
        completed: Any,
        next_steps: Any,
        open_questions: Any,
        validation: Any,
        expected_format: Any = AGENT_CHECKPOINT_FORMAT,
    ) -> dict[str, Any]:
        if expected_format != AGENT_CHECKPOINT_FORMAT:
            raise ValidationError(
                "INVALID_AGENT_CHECKPOINT",
                f"agent checkpoint format must be {AGENT_CHECKPOINT_FORMAT!r}",
            )
        if not isinstance(status, str) or status not in AGENT_CHECKPOINT_STATUSES:
            raise ValidationError(
                "INVALID_AGENT_CHECKPOINT",
                f"status must be one of {sorted(AGENT_CHECKPOINT_STATUSES)}",
            )
        return {
            "format": AGENT_CHECKPOINT_FORMAT,
            "objective": cls._text(
                "objective",
                objective,
                maximum=MAX_CHECKPOINT_OBJECTIVE_CHARS,
            ),
            "summary": cls._text(
                "summary",
                summary,
                maximum=MAX_CHECKPOINT_SUMMARY_CHARS,
            ),
            "status": status,
            "completed": cls._items("completed", completed),
            "next_steps": cls._items("next_steps", next_steps),
            "open_questions": cls._items("open_questions", open_questions),
            "validation": cls._items("validation", validation),
        }

    @staticmethod
    def _text(name: str, value: Any, *, maximum: int) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(
                "INVALID_AGENT_CHECKPOINT",
                f"{name} must be a non-empty string",
            )
        if len(value) > maximum:
            raise ValidationError(
                "INVALID_AGENT_CHECKPOINT",
                f"{name} must contain at most {maximum} characters",
            )
        return value

    @classmethod
    def _items(cls, name: str, values: Any) -> list[str]:
        if values is None:
            return []
        if not isinstance(values, list):
            raise ValidationError(
                "INVALID_AGENT_CHECKPOINT",
                f"{name} must be a list of strings or null",
            )
        if len(values) > MAX_CHECKPOINT_ITEMS:
            raise ValidationError(
                "INVALID_AGENT_CHECKPOINT",
                f"{name} may contain at most {MAX_CHECKPOINT_ITEMS} items",
            )
        normalized = [
            cls._text(f"{name} item", value, maximum=MAX_CHECKPOINT_ITEM_CHARS)
            for value in values
        ]
        if len(normalized) != len(set(normalized)):
            raise ValidationError(
                "INVALID_AGENT_CHECKPOINT",
                f"{name} must not contain duplicate items",
            )
        return normalized

    @staticmethod
    def _result(
        checkpoint: dict[str, Any] | None,
        *,
        configured: bool,
        project: str,
        branch: str,
        selected_revision_id: str,
        branch_head_revision_id: str,
        checkpoint_revision_id: str | None,
        checkpoint_id: str | None,
        checkpoint_hash: str | None,
    ) -> dict[str, Any]:
        return {
            "configured": configured,
            "project": project,
            "branch": branch,
            "revision_id": selected_revision_id,
            "branch_head_revision_id": branch_head_revision_id,
            "revision_is_branch_head": (
                selected_revision_id == branch_head_revision_id
            ),
            "checkpoint_revision_id": checkpoint_revision_id,
            "checkpoint_is_selected_revision": (
                checkpoint_revision_id == selected_revision_id
                if checkpoint_revision_id is not None
                else False
            ),
            "checkpoint_id": checkpoint_id,
            "checkpoint_hash": checkpoint_hash,
            "checkpoint": checkpoint,
            "resume": (
                {
                    "tool": "branch_resume_snapshot",
                    "arguments": {
                        "project": project,
                        "branch": branch,
                        "revision_id": checkpoint_revision_id,
                    },
                }
                if checkpoint_revision_id is not None
                else None
            ),
        }
