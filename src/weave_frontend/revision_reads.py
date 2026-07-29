"""Revision-pinned program rendering and stable-node search."""

from __future__ import annotations

from typing import Any, Protocol

from .errors import NotFoundError
from .revision_limits import MAX_NODE_FIND_RESULTS, require_bounded_int
from .sexpr import head_symbol, render_node


class _Workspace(Protocol):
    db: Any

    def branch_head(self, project: str, branch: str = "main") -> str: ...

    def _state_at_revision(self, revision_id: str) -> dict[str, dict[str, Any]]: ...


class RevisionReadService:
    """Read complete source views or node matches from one immutable revision."""

    def __init__(self, workspace: _Workspace) -> None:
        self.workspace = workspace

    def render(
        self,
        project: str,
        branch: str,
        document: str,
        *,
        annotated: bool = True,
        annotate_atoms: bool = False,
        revision_id: str | None = None,
    ) -> dict[str, Any]:
        """Render one document from a branch head or exact project revision."""

        selection, root = self._document(project, branch, document, revision_id)
        return {
            **selection,
            "document": document,
            "annotated": annotated,
            "annotate_atoms": annotate_atoms,
            "root_node_id": root["id"],
            "source": render_node(
                root,
                annotated=annotated,
                annotate_atoms=annotate_atoms,
            ),
        }

    def find(
        self,
        project: str,
        branch: str,
        document: str,
        *,
        head: str | None = None,
        kind: str | None = None,
        value: Any | None = None,
        limit: int = 50,
        revision_id: str | None = None,
    ) -> dict[str, Any]:
        """Find stable nodes in one document from an exact immutable state."""

        effective_limit = require_bounded_int(
            limit,
            code="INVALID_NODE_FIND_LIMIT",
            name="limit",
            minimum=1,
            maximum=MAX_NODE_FIND_RESULTS,
        )
        selection, root = self._document(project, branch, document, revision_id)
        matches: list[dict[str, Any]] = []
        total_match_count = 0
        stack: list[tuple[dict[str, Any], str | None, int | None]] = [
            (root, None, None)
        ]
        while stack:
            node, parent_id, position = stack.pop()
            matches_filter = (
                (head is None or head_symbol(node) == head)
                and (kind is None or node.get("kind") == kind)
                and (value is None or node.get("value") == value)
            )
            if matches_filter:
                total_match_count += 1
                if len(matches) < effective_limit:
                    matches.append(
                        {
                            "node_id": node["id"],
                            "kind": node["kind"],
                            "head": head_symbol(node),
                            "value": node.get("value"),
                            "parent_id": parent_id,
                            "position": position,
                        }
                    )
            children = node.get("children") if node.get("kind") == "list" else None
            if isinstance(children, list):
                node_id = str(node["id"])
                for index in range(len(children) - 1, -1, -1):
                    stack.append((children[index], node_id, index))

        truncated = total_match_count > len(matches)
        return {
            **selection,
            "document": document,
            "limit": effective_limit,
            "returned_count": len(matches),
            "matched_count": len(matches),
            "total_match_count": total_match_count,
            "truncated": truncated,
            "has_more": truncated,
            "limits": {"maximum_results": MAX_NODE_FIND_RESULTS},
            "matches": matches,
        }

    def _document(
        self,
        project: str,
        branch: str,
        document: str,
        revision_id: str | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
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
        return (
            {
                "project": project,
                "branch": branch,
                "branch_head_revision_id": branch_head,
                "revision_id": selected_revision,
                "revision_is_branch_head": selected_revision == branch_head,
            },
            root,
        )

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
