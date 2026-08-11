"""Conflict-aware immutable reverts built on Jacquard's stable-ID merge engine."""

from __future__ import annotations

from typing import Any

from .builds import validate_build_target_references
from .errors import ConflictError, NotFoundError, ValidationError
from .merges import MergePreviewService
from .task_contracts import validate_task_contract_references
from .test_target_validation import validate_test_target_references

REVERT_PREVIEW_FORMAT = "weave-revert-preview-v1"
MAX_REVERT_HISTORY_SCAN = 100_000


class RevertService:
    """Preview and publish inverse first-parent changes without rewriting history."""

    def __init__(self, workspace: Any, previews: MergePreviewService) -> None:
        self.workspace = workspace
        self.previews = previews

    def preview(
        self,
        project: str,
        branch: str,
        revision_id: str,
    ) -> dict[str, Any]:
        """Return one deterministic inverse-change preview against the current head."""

        return self._public(self._snapshot(project, branch, revision_id))

    def revert(
        self,
        project: str,
        branch: str,
        revision_id: str,
        *,
        preview_id: str,
        author: str = "revert-agent",
        message: str | None = None,
    ) -> dict[str, Any]:
        """Publish one reviewed inverse as a new immutable branch revision."""

        if not isinstance(preview_id, str) or not preview_id:
            raise ValidationError(
                "INVALID_REVERT_PREVIEW_ID",
                "preview_id must be a non-empty string",
            )
        snapshot = self._snapshot(project, branch, revision_id)
        if preview_id != snapshot["preview_id"]:
            raise ValidationError(
                "STALE_REVERT_PREVIEW",
                "the branch head or selected revision identity changed after preview",
            )
        if not snapshot["revertible"]:
            raise ConflictError(list(snapshot["conflicts"]))
        if not snapshot["would_change_branch"]:
            raise ValidationError(
                "REVERT_NO_CHANGES",
                "the reviewed inverse would not change the current branch state",
            )
        state = snapshot.get("_reverted_state")
        if not isinstance(state, dict):
            raise ValidationError(
                "INVALID_REVERT_PREVIEW",
                "a revertible preview did not retain its prospective state",
            )

        current_head = str(snapshot["branch_head_revision_id"])
        new_revision_id = self.workspace._commit(
            project,
            branch,
            state,
            message=message or f"revert revision {revision_id}",
            author=author,
            operations=[
                (
                    "revert",
                    branch,
                    {
                        "format": REVERT_PREVIEW_FORMAT,
                        "preview_id": preview_id,
                        "reverted_revision_id": revision_id,
                        "reverted_parent_revision_id": snapshot[
                            "reverted_parent_revision_id"
                        ],
                        "reviewed_branch_head_revision_id": current_head,
                        "prospective_root_hash": snapshot["prospective_root_hash"],
                        "changed_documents": snapshot["changed_documents"],
                    },
                )
            ],
            expected_branch_heads={branch: current_head},
            stale_error_code="STALE_REVERT_PREVIEW",
        )
        return {
            "format": "weave-revert-result-v1",
            "project": project,
            "branch": branch,
            "revision_id": new_revision_id,
            "parent_revision_id": current_head,
            "reverted_revision_id": revision_id,
            "reverted_parent_revision_id": snapshot["reverted_parent_revision_id"],
            "preview_id": preview_id,
            "preview_enforced": True,
            "root_hash": snapshot["prospective_root_hash"],
            "changed_documents": snapshot["changed_documents"],
            "document_changes": snapshot["document_changes"],
            "history_rewritten": False,
        }

    def _snapshot(
        self,
        project: str,
        branch: str,
        revision_id: str,
    ) -> dict[str, Any]:
        self._validate_revision_id(revision_id)
        branch_head = self.workspace.branch_head(project, branch)
        selected = self._revision(project, revision_id)
        parent_revision_id = selected["parent1_revision_id"]
        if parent_revision_id is None:
            raise ValidationError(
                "INITIAL_REVISION_NOT_REVERTIBLE",
                "the initial project revision has no first-parent change to invert",
            )
        self._require_first_parent_reachable(branch_head, revision_id)

        payload = {
            "format": REVERT_PREVIEW_FORMAT,
            "project": project,
            "branch": branch,
            "branch_head_revision_id": branch_head,
            "reverted_revision_id": revision_id,
            "reverted_parent_revision_id": parent_revision_id,
        }
        preview_id = self.workspace.db.hash_value(payload)
        selected_state = self.workspace._state_at_revision(revision_id)
        current_state = self.workspace._state_at_revision(branch_head)
        parent_state = self.workspace._state_at_revision(parent_revision_id)
        try:
            reverted_state, changed = self.workspace._merge_states(
                selected_state,
                current_state,
                parent_state,
            )
            self.workspace._validate_state(reverted_state)
            validate_build_target_references(reverted_state)
            validate_test_target_references(reverted_state)
            validate_task_contract_references(reverted_state)
        except ConflictError as exc:
            return {
                **payload,
                "preview_id": preview_id,
                "revertible": False,
                "conflicts": tuple(exc.conflicts),
                "would_change_branch": False,
                "changed_documents": (),
                "document_changes": (),
                "current_root_hash": self._root_hash(branch_head),
                "reverted_revision_root_hash": selected["root_hash"],
                "reverted_parent_root_hash": self._root_hash(parent_revision_id),
                "prospective_root_hash": None,
                "_reverted_state": None,
            }

        document_changes = self.previews._document_changes(current_state, reverted_state)
        return {
            **payload,
            "preview_id": preview_id,
            "revertible": True,
            "conflicts": (),
            "would_change_branch": reverted_state != current_state,
            "changed_documents": tuple(sorted(changed)),
            "document_changes": tuple(document_changes),
            "current_root_hash": self._root_hash(branch_head),
            "reverted_revision_root_hash": selected["root_hash"],
            "reverted_parent_root_hash": self._root_hash(parent_revision_id),
            "prospective_root_hash": self.workspace.db.hash_value(reverted_state),
            "_reverted_state": reverted_state,
        }

    def _require_first_parent_reachable(self, head: str, selected: str) -> None:
        current: str | None = head
        scanned = 0
        while current is not None and scanned < MAX_REVERT_HISTORY_SCAN:
            if current == selected:
                return
            row = self.workspace.db.connection.execute(
                "SELECT parent1_id FROM revisions WHERE id = ?",
                (current,),
            ).fetchone()
            current = str(row["parent1_id"]) if row and row["parent1_id"] else None
            scanned += 1
        if current is not None:
            raise ValidationError(
                "REVERT_HISTORY_SCAN_LIMIT",
                f"first-parent reachability exceeded {MAX_REVERT_HISTORY_SCAN} revisions",
            )
        raise ValidationError(
            "REVISION_NOT_ON_BRANCH",
            f"revision {selected!r} is not in the branch's first-parent history",
        )

    def _revision(self, project: str, revision_id: str) -> dict[str, Any]:
        row = self.workspace.db.connection.execute(
            """SELECT r.id, r.parent1_id, r.parent2_id, r.root_hash
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
            "revision_id": str(row["id"]),
            "parent1_revision_id": (
                str(row["parent1_id"]) if row["parent1_id"] is not None else None
            ),
            "parent2_revision_id": (
                str(row["parent2_id"]) if row["parent2_id"] is not None else None
            ),
            "root_hash": str(row["root_hash"]),
        }

    def _root_hash(self, revision_id: str) -> str:
        row = self.workspace.db.connection.execute(
            "SELECT root_hash FROM revisions WHERE id = ?",
            (revision_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"revision {revision_id!r} not found")
        return str(row["root_hash"])

    @staticmethod
    def _validate_revision_id(value: Any) -> None:
        if not isinstance(value, str) or not value:
            raise ValidationError(
                "INVALID_REVISION_ID",
                "revision_id must be a non-empty string",
            )

    @staticmethod
    def _public(snapshot: dict[str, Any]) -> dict[str, Any]:
        return {
            key: list(value) if isinstance(value, tuple) else value
            for key, value in snapshot.items()
            if not key.startswith("_")
        }
