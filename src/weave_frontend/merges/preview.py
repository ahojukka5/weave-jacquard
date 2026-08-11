"""Deterministic two-phase previews for stable-ID branch merges."""

from __future__ import annotations

from collections import Counter
from typing import Any, Protocol

from ..errors import ConflictError, ValidationError
from ..revision_dag import RevisionDagAnalysis
from ..sexpr import head_symbol

MERGE_PREVIEW_FORMAT = "weave-merge-preview-v1"


class _Workspace(Protocol):
    db: Any

    def branch_head(self, project: str, branch: str = "main") -> str: ...

    def _common_ancestor_analysis(
        self,
        left: str,
        right: str,
    ) -> RevisionDagAnalysis: ...

    def _state_at_revision(self, revision_id: str) -> dict[str, dict[str, Any]]: ...

    @classmethod
    def _merge_states(
        cls,
        base: dict[str, dict[str, Any]],
        ours: dict[str, dict[str, Any]],
        theirs: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, dict[str, Any]], set[str]]: ...

    @classmethod
    def _validate_state(cls, state: dict[str, dict[str, Any]]) -> None: ...

    def merge(
        self,
        project: str,
        *,
        target_branch: str,
        source_branch: str,
        author: str = "merge-agent",
        expected_target_head: str | None = None,
        expected_source_head: str | None = None,
    ) -> Any: ...


class MergePreviewService:
    """Preview and publish merges against the exact heads that were reviewed."""

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

    def preview(
        self,
        project: str,
        target_branch: str,
        source_branch: str,
    ) -> dict[str, Any]:
        snapshot = self._snapshot(project, target_branch, source_branch)
        return self._public_preview(snapshot)

    def candidate(
        self,
        project: str,
        target_branch: str,
        source_branch: str,
    ) -> dict[str, Any]:
        return self._snapshot(project, target_branch, source_branch)

    def merge(
        self,
        project: str,
        target_branch: str,
        source_branch: str,
        *,
        preview_id: str | None = None,
        author: str = "merge-agent",
    ) -> dict[str, Any]:
        snapshot: dict[str, Any] | None = None
        if preview_id is not None:
            if not isinstance(preview_id, str) or not preview_id:
                raise ValidationError(
                    "INVALID_MERGE_PREVIEW_ID",
                    "preview_id must be a non-empty string",
                )
            snapshot = self._snapshot(project, target_branch, source_branch)
            if preview_id != snapshot["preview_id"]:
                raise ValidationError(
                    "STALE_MERGE_PREVIEW",
                    "one or both branch heads changed after the merge preview",
                )
            if not snapshot["mergeable"]:
                raise ConflictError(list(snapshot["conflicts"]))

        result = self.workspace.merge(
            project,
            target_branch=target_branch,
            source_branch=source_branch,
            author=author,
            expected_target_head=(
                str(snapshot["target_head_revision_id"])
                if snapshot is not None
                else None
            ),
            expected_source_head=(
                str(snapshot["source_head_revision_id"])
                if snapshot is not None
                else None
            ),
        )
        return {
            "revision_id": result.revision_id,
            "target_branch": result.target_branch,
            "source_branch": result.source_branch,
            "changed_symbols": list(result.changed_symbols),
            "preview_id": preview_id,
            "preview_enforced": preview_id is not None,
            "reviewed_base_revision_id": (
                snapshot["base_revision_id"] if snapshot is not None else None
            ),
            "reviewed_target_head_revision_id": (
                snapshot["target_head_revision_id"] if snapshot is not None else None
            ),
            "reviewed_source_head_revision_id": (
                snapshot["source_head_revision_id"] if snapshot is not None else None
            ),
        }

    def _snapshot(
        self,
        project: str,
        target_branch: str,
        source_branch: str,
    ) -> dict[str, Any]:
        target_head = self.workspace.branch_head(project, target_branch)
        source_head = self.workspace.branch_head(project, source_branch)
        ancestry = self.workspace._common_ancestor_analysis(target_head, source_head)
        base = ancestry.require_single_best()
        preview_payload = {
            "format": MERGE_PREVIEW_FORMAT,
            "project": project,
            "target_branch": target_branch,
            "source_branch": source_branch,
            "base_revision_id": base,
            "target_head_revision_id": target_head,
            "source_head_revision_id": source_head,
            "ancestry": ancestry.evidence(),
        }
        preview_id = self.workspace.db.hash_value(preview_payload)

        base_state = self.workspace._state_at_revision(base)
        target_state = self.workspace._state_at_revision(target_head)
        source_state = self.workspace._state_at_revision(source_head)
        try:
            merged_state, changed = self.workspace._merge_states(
                base_state,
                target_state,
                source_state,
            )
            self.workspace._validate_state(merged_state)
        except ConflictError as exc:
            return {
                **preview_payload,
                "preview_id": preview_id,
                "mergeable": False,
                "conflicts": tuple(exc.conflicts),
                "changed_documents": (),
                "document_changes": (),
                "merged_root_hash": None,
                "target_root_hash": self._revision_root_hash(target_head),
                "source_root_hash": self._revision_root_hash(source_head),
                "_merged_state": None,
            }

        document_changes = self._document_changes(target_state, merged_state)
        return {
            **preview_payload,
            "preview_id": preview_id,
            "mergeable": True,
            "conflicts": (),
            "changed_documents": tuple(sorted(changed)),
            "document_changes": tuple(document_changes),
            "merged_root_hash": self.workspace.db.hash_value(merged_state),
            "target_root_hash": self._revision_root_hash(target_head),
            "source_root_hash": self._revision_root_hash(source_head),
            "_merged_state": merged_state,
        }

    @staticmethod
    def _public_preview(snapshot: dict[str, Any]) -> dict[str, Any]:
        return {
            key: list(value) if isinstance(value, tuple) else value
            for key, value in snapshot.items()
            if not key.startswith("_")
        }

    def _revision_root_hash(self, revision_id: str) -> str:
        row = self.workspace.db.connection.execute(
            "SELECT root_hash FROM revisions WHERE id = ?",
            (revision_id,),
        ).fetchone()
        if row is None:
            raise ValidationError(
                "INVALID_MERGE_REVISION",
                f"revision {revision_id!r} has no stored root hash",
            )
        return str(row["root_hash"])

    def _document_changes(
        self,
        before_state: dict[str, dict[str, Any]],
        after_state: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for document in sorted(set(before_state) | set(after_state)):
            before = before_state.get(document)
            after = after_state.get(document)
            if before == after:
                continue
            summary = self._node_change_summary(before, after)
            if before is None:
                status = "added"
            elif after is None:
                status = "removed"
            else:
                status = "modified"
            result.append(
                {
                    "document": document,
                    "status": status,
                    "before_hash": (
                        self.workspace.db.hash_value(before)
                        if before is not None
                        else None
                    ),
                    "after_hash": (
                        self.workspace.db.hash_value(after)
                        if after is not None
                        else None
                    ),
                    **summary,
                }
            )
        return result

    def _node_change_summary(
        self,
        before_root: dict[str, Any] | None,
        after_root: dict[str, Any] | None,
    ) -> dict[str, Any]:
        before, before_order = self._flatten(before_root)
        after, after_order = self._flatten(after_root)
        kinds: Counter[str] = Counter()
        changed_node_count = 0

        for node_id in after_order:
            after_value = after[node_id]
            before_value = before.get(node_id)
            if before_value is None:
                kinds["added"] += 1
                changed_node_count += 1
                continue
            node_kinds = [
                change_kind
                for field, change_kind in self._FIELDS
                if before_value[field] != after_value[field]
            ]
            if node_kinds:
                kinds.update(node_kinds)
                changed_node_count += 1

        for node_id in before_order:
            if node_id not in after:
                kinds["removed"] += 1
                changed_node_count += 1

        return {
            "before_node_count": len(before),
            "after_node_count": len(after),
            "changed_node_count": changed_node_count,
            "change_kind_counts": dict(sorted(kinds.items())),
        }

    @staticmethod
    def _flatten(
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
