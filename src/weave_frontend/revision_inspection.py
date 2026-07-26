"""Revision-pinned stable-node inspection for agent repair workflows."""

from __future__ import annotations

from typing import Any, Protocol

from .errors import NotFoundError
from .sexpr import find_node, find_parent, head_symbol, render_node


class _Workspace(Protocol):
    db: Any
    grammar: Any

    def branch_head(self, project: str, branch: str = "main") -> str: ...

    def _state_at_revision(self, revision_id: str) -> dict[str, dict[str, Any]]: ...

    @classmethod
    def _truncate(cls, node: dict[str, Any], depth: int) -> dict[str, Any]: ...


class RevisionNodeInspectionService:
    """Read one local subtree from a branch head or exact immutable revision."""

    def __init__(self, workspace: _Workspace) -> None:
        self.workspace = workspace

    def inspect(
        self,
        project: str,
        branch: str,
        document: str,
        node_id: str,
        *,
        depth: int = 3,
        revision_id: str | None = None,
    ) -> dict[str, Any]:
        """Inspect a stable node without advancing or rewriting any branch."""

        branch_head = self.workspace.branch_head(project, branch)
        selected_revision = revision_id or branch_head
        if revision_id is not None:
            self._require_project_revision(project, revision_id)

        state = self.workspace._state_at_revision(selected_revision)
        try:
            root = state[document]
        except KeyError as exc:
            raise NotFoundError(
                f"document {document!r} not found in revision {selected_revision!r}"
            ) from exc

        node = find_node(root, node_id)
        try:
            parent, index = find_parent(root, node_id)
            parent_id: str | None = str(parent["id"])
        except NotFoundError:
            parent_id = None
            index = 0

        subtree = self.workspace._truncate(node, max(0, depth))
        return {
            "project": project,
            "document": document,
            "branch": branch,
            "branch_head_revision_id": branch_head,
            "revision_id": selected_revision,
            "revision_is_branch_head": selected_revision == branch_head,
            "node_id": node_id,
            "kind": node["kind"],
            "head": head_symbol(node),
            "parent_id": parent_id,
            "position": index if parent_id else None,
            "subtree": subtree,
            "annotated_weave": render_node(subtree, annotated=True),
            "grammar_hint": self.workspace.grammar.hint_for_node(node),
        }

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
