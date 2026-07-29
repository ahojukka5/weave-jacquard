"""Bounded stable-node diffs between immutable program revisions."""

from __future__ import annotations

from collections import Counter
from typing import Any, Protocol

from .errors import NotFoundError
from .revision_limits import (
    MAX_REVISION_DIFF_PAGE_SIZE,
    require_bounded_int,
    require_nonnegative_int,
)
from .sexpr import head_symbol


class _Workspace(Protocol):
    db: Any

    def branch_head(self, project: str, branch: str = "main") -> str: ...

    def _state_at_revision(self, revision_id: str) -> dict[str, dict[str, Any]]: ...


class RevisionNodeDiffService:
    """Compare one document across two project-owned immutable revisions."""

    _FIELDS = (
        ("kind", "kind_changed"),
        ("head", "head_changed"),
        ("value", "value_changed"),
        ("parent_id", "parent_changed"),
        ("position", "position_changed"),
        ("child_count", "child_count_changed"),
    )

    def __init__(self, workspace: _Workspace) -> None:
        self.workspace = workspace

    def page(
        self,
        project: str,
        document: str,
        base_revision_id: str,
        *,
        branch: str = "main",
        target_revision_id: str | None = None,
        start_index: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Return one immutable, deterministic page of stable-node changes."""

        effective_start = require_nonnegative_int(
            start_index,
            code="INVALID_REVISION_DIFF_INDEX",
            name="start_index",
        )
        effective_limit = require_bounded_int(
            limit,
            code="INVALID_REVISION_DIFF_LIMIT",
            name="limit",
            minimum=1,
            maximum=MAX_REVISION_DIFF_PAGE_SIZE,
        )
        self._require_project_revision(project, base_revision_id)

        branch_head = self.workspace.branch_head(project, branch)
        target_revision = target_revision_id or branch_head
        if target_revision_id is not None:
            self._require_project_revision(project, target_revision_id)

        base_state = self.workspace._state_at_revision(base_revision_id)
        target_state = self.workspace._state_at_revision(target_revision)
        base_root = base_state.get(document)
        target_root = target_state.get(document)
        if base_root is None and target_root is None:
            raise NotFoundError(
                f"document {document!r} is absent from revisions "
                f"{base_revision_id!r} and {target_revision!r}"
            )

        before, before_order = self._flatten(base_root)
        after, after_order = self._flatten(target_root)
        changes = self._changes(before, before_order, after, after_order)
        counts = Counter(
            kind for change in changes for kind in change["change_kinds"]
        )

        page = changes[effective_start : effective_start + effective_limit]
        next_index = effective_start + len(page)
        has_more = next_index < len(changes)
        return {
            "project": project,
            "document": document,
            "branch": branch,
            "branch_head_revision_id": branch_head,
            "base_revision_id": base_revision_id,
            "target_revision_id": target_revision,
            "target_revision_is_branch_head": target_revision == branch_head,
            "base_document_present": base_root is not None,
            "target_document_present": target_root is not None,
            "base_node_count": len(before),
            "target_node_count": len(after),
            "total_change_count": len(changes),
            "change_kind_counts": dict(sorted(counts.items())),
            "start_index": effective_start,
            "limit": effective_limit,
            "returned_count": len(page),
            "has_more": has_more,
            "truncated": has_more,
            "next_index": next_index if has_more else None,
            "limits": {"maximum_page_size": MAX_REVISION_DIFF_PAGE_SIZE},
            "changes": page,
        }

    @classmethod
    def _changes(
        cls,
        before: dict[str, dict[str, Any]],
        before_order: list[str],
        after: dict[str, dict[str, Any]],
        after_order: list[str],
    ) -> list[dict[str, Any]]:
        changes: list[dict[str, Any]] = []
        for node_id in after_order:
            after_value = after[node_id]
            before_value = before.get(node_id)
            if before_value is None:
                changes.append(
                    {
                        "node_id": node_id,
                        "change_kinds": ["added"],
                        "before": None,
                        "after": after_value,
                    }
                )
                continue

            kinds = [
                change_kind
                for field, change_kind in cls._FIELDS
                if before_value[field] != after_value[field]
            ]
            if kinds:
                changes.append(
                    {
                        "node_id": node_id,
                        "change_kinds": kinds,
                        "before": before_value,
                        "after": after_value,
                    }
                )

        for node_id in before_order:
            if node_id not in after:
                changes.append(
                    {
                        "node_id": node_id,
                        "change_kinds": ["removed"],
                        "before": before[node_id],
                        "after": None,
                    }
                )
        return changes

    @classmethod
    def _flatten(
        cls,
        root: dict[str, Any] | None,
    ) -> tuple[dict[str, dict[str, Any]], list[str]]:
        nodes: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        if root is None:
            return nodes, order

        def visit(
            node: dict[str, Any],
            parent_id: str | None,
            position: int | None,
        ) -> None:
            node_id = str(node["id"])
            children = node.get("children") if node.get("kind") == "list" else None
            nodes[node_id] = {
                "node_id": node_id,
                "kind": node["kind"],
                "head": head_symbol(node),
                "value": node.get("value"),
                "parent_id": parent_id,
                "position": position,
                "child_count": len(children) if isinstance(children, list) else 0,
            }
            order.append(node_id)
            if isinstance(children, list):
                for index, child in enumerate(children):
                    visit(child, node_id, index)

        visit(root, None, None)
        return nodes, order

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

    @staticmethod
    def _validate_start_index(start_index: int) -> None:
        require_nonnegative_int(
            start_index,
            code="INVALID_REVISION_DIFF_INDEX",
            name="start_index",
        )

    @staticmethod
    def _validate_limit(limit: int) -> None:
        require_bounded_int(
            limit,
            code="INVALID_REVISION_DIFF_LIMIT",
            name="limit",
            minimum=1,
            maximum=MAX_REVISION_DIFF_PAGE_SIZE,
        )
