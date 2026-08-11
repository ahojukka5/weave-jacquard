"""Bounded stable project-wide branch and agent checkpoint supervision."""

from __future__ import annotations

from typing import Any

from ..errors import NotFoundError, ValidationError
from .checkpoint import AGENT_CHECKPOINT_OPERATION, AgentCheckpointRegistry

PROJECT_AGENT_STATUS_FORMAT = "weave-project-agent-status-v1"
PROJECT_AGENT_STATUS_CATALOG_FORMAT = "weave-project-agent-status-catalog-v1"
MAX_AGENT_STATUS_PAGE = 100
MAX_AGENT_STATUS_BRANCH_CATALOG = 1_000
MAX_AGENT_STATUS_CHECKPOINT_SCAN = 500


class ProjectAgentStatusService:
    """Page exact branch heads with bounded verified checkpoint orientation."""

    def __init__(self, checkpoints: AgentCheckpointRegistry) -> None:
        self.checkpoints = checkpoints
        self.workspace = checkpoints.workspace

    def page(
        self,
        project: str,
        *,
        start_after_branch: str | None = None,
        catalog_id: str | None = None,
        limit: int = 25,
        checkpoint_scan_limit: int = 100,
    ) -> dict[str, Any]:
        """Return one stable lexical page across current project branch heads."""

        self._validate_limit("limit", limit, MAX_AGENT_STATUS_PAGE)
        self._validate_limit(
            "checkpoint_scan_limit",
            checkpoint_scan_limit,
            MAX_AGENT_STATUS_CHECKPOINT_SCAN,
        )
        project_id = self.workspace.project_id(project)
        members = self._catalog_members(project_id)
        effective_catalog_id = self.workspace.db.hash_value(
            {
                "format": PROJECT_AGENT_STATUS_CATALOG_FORMAT,
                "project": project,
                "members": members,
            }
        )
        self._validate_optional_id("catalog_id", catalog_id)
        if catalog_id is not None and catalog_id != effective_catalog_id:
            raise ValidationError(
                "STALE_AGENT_STATUS_CATALOG",
                "project branch heads changed since the requested agent-status catalog",
            )
        self._validate_optional_id("start_after_branch", start_after_branch)
        names = [member["branch"] for member in members]
        if start_after_branch is None:
            start_index = 0
        else:
            try:
                start_index = names.index(start_after_branch) + 1
            except ValueError as exc:
                raise ValidationError(
                    "INVALID_AGENT_STATUS_CURSOR",
                    "start_after_branch must identify a branch in the current catalog",
                ) from exc

        selected = members[start_index : start_index + limit]
        statuses = [
            self._branch_status(
                project,
                member,
                checkpoint_scan_limit=checkpoint_scan_limit,
            )
            for member in selected
        ]
        end_index = start_index + len(selected)
        has_more = end_index < len(members)
        result: dict[str, Any] = {
            "format": PROJECT_AGENT_STATUS_FORMAT,
            "project": project,
            "catalog_id": effective_catalog_id,
            "branch_catalog_count": len(members),
            "start_after_branch": start_after_branch,
            "limit": limit,
            "checkpoint_scan_limit": checkpoint_scan_limit,
            "returned_branch_count": len(statuses),
            "has_more": has_more,
            "next_after_branch": selected[-1]["branch"] if has_more and selected else None,
            "branches": statuses,
            "ordering": "lexical branch name within one exact branch-head catalog",
            "interpretation_note": (
                "checkpoint lag and root-hash drift are structural evidence only; they do "
                "not prove inactivity, correctness, completion, or review readiness"
            ),
        }
        result["page_id"] = self.workspace.db.hash_value(result)
        return result

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
                "AGENT_STATUS_BRANCH_FANOUT_EXCEEDED",
                "project agent status supports at most "
                f"{MAX_AGENT_STATUS_BRANCH_CATALOG} branches",
            )
        return [
            {
                "branch": str(row["name"]),
                "head_revision_id": str(row["head_revision_id"]),
            }
            for row in rows
        ]

    def _branch_status(
        self,
        project: str,
        member: dict[str, str],
        *,
        checkpoint_scan_limit: int,
    ) -> dict[str, Any]:
        branch = member["branch"]
        head_revision_id = member["head_revision_id"]
        head = self._revision(project, head_revision_id)
        current: str | None = head_revision_id
        revisions_scanned = 0
        revisions_since_checkpoint = 0
        checkpoint_view: dict[str, Any] | None = None
        checkpoint_revision: dict[str, Any] | None = None

        while current is not None and revisions_scanned < checkpoint_scan_limit:
            revision = self._revision(project, current)
            checkpoint = self._checkpoint_at_revision(project, current)
            revisions_scanned += 1
            if checkpoint is not None:
                checkpoint_view = checkpoint
                checkpoint_revision = revision
                break
            revisions_since_checkpoint += 1
            current = revision["parent1_id"]

        scan_limit_reached = (
            checkpoint_view is None
            and current is not None
            and revisions_scanned == checkpoint_scan_limit
        )
        complete_history_scanned = checkpoint_view is None and current is None
        if checkpoint_view is None:
            checkpoint_state = (
                "not_found_within_scan"
                if scan_limit_reached
                else "none_in_first_parent_history"
            )
            checkpoint_summary = None
            program_state_changed_since_checkpoint = None
            checkpoint_is_head = False
        else:
            assert checkpoint_revision is not None
            checkpoint_state = "head" if revisions_since_checkpoint == 0 else "behind_head"
            checkpoint = checkpoint_view["checkpoint"]
            checkpoint_summary = {
                "checkpoint_revision_id": checkpoint_revision["id"],
                "checkpoint_id": checkpoint_view["checkpoint_id"],
                "checkpoint_hash": checkpoint_view["checkpoint_hash"],
                "created_at": checkpoint_revision["created_at"],
                "author": checkpoint_revision["author"],
                "root_hash": checkpoint_revision["root_hash"],
                "status": checkpoint["status"],
                "objective": checkpoint["objective"],
                "completed_count": len(checkpoint["completed"]),
                "next_step_count": len(checkpoint["next_steps"]),
                "open_question_count": len(checkpoint["open_questions"]),
                "validation_count": len(checkpoint["validation"]),
                "resume": {
                    "tool": "branch_resume_snapshot",
                    "arguments": {
                        "project": project,
                        "branch": branch,
                        "revision_id": checkpoint_revision["id"],
                    },
                },
            }
            program_state_changed_since_checkpoint = (
                head["root_hash"] != checkpoint_revision["root_hash"]
            )
            checkpoint_is_head = checkpoint_revision["id"] == head_revision_id

        return {
            "branch": branch,
            "head_revision_id": head_revision_id,
            "head": {
                "root_hash": head["root_hash"],
                "parent1_id": head["parent1_id"],
                "parent2_id": head["parent2_id"],
                "message": head["message"],
                "author": head["author"],
                "created_at": head["created_at"],
            },
            "checkpoint_state": checkpoint_state,
            "checkpoint_is_head": checkpoint_is_head,
            "checkpoint": checkpoint_summary,
            "revisions_scanned": revisions_scanned,
            "revisions_since_checkpoint": (
                revisions_since_checkpoint if checkpoint_view is not None else None
            ),
            "checkpoint_scan_limit_reached": scan_limit_reached,
            "complete_first_parent_history_scanned": complete_history_scanned,
            "checkpoint_lag_lower_bound": (
                revisions_scanned if scan_limit_reached else None
            ),
            "program_state_changed_since_checkpoint": (
                program_state_changed_since_checkpoint
            ),
            "resume_head": {
                "tool": "branch_resume_snapshot",
                "arguments": {
                    "project": project,
                    "branch": branch,
                    "revision_id": head_revision_id,
                },
            },
        }

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
        payload = self.checkpoints._operation_payload(str(row["payload_json"]))
        checkpoint_id = payload["document_id"]
        checkpoint = self.checkpoints._read_document(project, checkpoint_id)
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

    @staticmethod
    def _validate_limit(name: str, value: Any, maximum: int) -> None:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 1
            or value > maximum
        ):
            raise ValidationError(
                "INVALID_AGENT_STATUS_LIMIT",
                f"{name} must be an integer between 1 and {maximum}",
            )

    @staticmethod
    def _validate_optional_id(name: str, value: Any) -> None:
        if value is not None and (not isinstance(value, str) or not value):
            raise ValidationError(
                "INVALID_AGENT_STATUS_CURSOR",
                f"{name} must be a non-empty string or null",
            )
