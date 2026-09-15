"""Compact structural observation for agent modification workflows."""

from __future__ import annotations

from typing import Any, Protocol

from .errors import NotFoundError, ValidationError
from .sexpr import (
    JsonObject,
    find_node,
    find_parent,
    head_symbol,
    render_node,
    walk_nodes,
)

DECLARATION_HEADS = frozenset(
    {
        "fn",
        "entry",
        "type",
        "const",
        "import",
        "export",
        "global",
    }
)


class _Workspace(Protocol):
    db: Any

    def branch_head(self, project: str, branch: str = "main") -> str: ...

    def _state_at_revision(self, revision_id: str) -> dict[str, JsonObject]: ...


def identity_contract() -> dict[str, Any]:
    """Describe when a stable node identity remains usable."""

    return {
        "survives": [
            "atom value edits keep the same node ID",
            "moving a node to another parent preserves its ID",
            "wrapping a node preserves the wrapped node's ID",
            "sibling inserts and unrelated edits leave surviving IDs unchanged",
        ],
        "changes": [
            "creating a form or atom assigns a new ID",
            "copying or importing a tree assigns new IDs",
            "wrapping a node creates a new wrapper ID",
        ],
        "invalid": [
            "deleting a node or any ancestor invalidates that ID",
            "IDs are revision-scoped: a missing ID is not guessed by name",
        ],
        "ambiguity": (
            "Name lookup reports AMBIGUOUS_TARGET with every matching ID. "
            "Jacquard never silently picks one of several declarations."
        ),
    }


def declaration_name(node: JsonObject) -> str | None:
    """Return the observational name of a declaration form, if present."""

    if node.get("kind") != "list":
        return None
    children = node.get("children")
    if not isinstance(children, list) or len(children) < 2:
        return None
    name_node = children[1]
    if name_node.get("kind") in {"symbol", "string"}:
        value = name_node.get("value")
        return str(value) if value is not None else None
    return None


class EntityCatalogService:
    """List and inspect named declarations without rendering whole files."""

    def __init__(self, workspace: _Workspace) -> None:
        self.workspace = workspace

    def list_entities(
        self,
        project: str,
        branch: str,
        document: str,
        *,
        revision_id: str | None = None,
        head: str | None = None,
    ) -> dict[str, Any]:
        selection, root = self._document(project, branch, document, revision_id)
        entities: list[dict[str, Any]] = []
        for node in walk_nodes(root):
            form = head_symbol(node)
            if form is None or form not in DECLARATION_HEADS:
                continue
            if head is not None and form != head:
                continue
            parent_id, position = self._parent_location(root, str(node["id"]))
            entities.append(
                {
                    "node_id": node["id"],
                    "kind": form,
                    "name": declaration_name(node),
                    "parent_id": parent_id,
                    "position": position,
                }
            )
        return {
            **selection,
            "document": document,
            "identity": identity_contract(),
            "count": len(entities),
            "entities": entities,
        }

    def inspect_entity(
        self,
        project: str,
        branch: str,
        document: str,
        *,
        node_id: str | None = None,
        kind: str | None = None,
        name: str | None = None,
        revision_id: str | None = None,
        depth: int = 2,
    ) -> dict[str, Any]:
        selection, root = self._document(project, branch, document, revision_id)
        resolved = self._resolve(root, node_id=node_id, kind=kind, name=name)
        node = find_node(root, str(resolved["node_id"]))
        parent_id, position = self._parent_location(root, str(node["id"]))
        children: list[dict[str, Any]] = []
        if node.get("kind") == "list":
            for index, child in enumerate(node.get("children") or []):
                children.append(
                    {
                        "node_id": child.get("id"),
                        "kind": child.get("kind"),
                        "head": head_symbol(child),
                        "name": declaration_name(child),
                        "position": index,
                    }
                )
        subtree = node if depth < 0 else self._truncate(node, depth)
        return {
            **selection,
            "document": document,
            "identity_status": "present",
            "node_id": node["id"],
            "kind": resolved["kind"] or head_symbol(node),
            "name": resolved["name"] or declaration_name(node),
            "parent_id": parent_id,
            "position": position,
            "children": children,
            "signature": self._signature(node),
            "annotated_weave": render_node(subtree, annotated=True),
        }

    def inspect_identity(
        self,
        project: str,
        branch: str,
        document: str,
        node_id: str,
        *,
        revision_id: str | None = None,
    ) -> dict[str, Any]:
        selection, root = self._document(project, branch, document, revision_id)
        try:
            node = find_node(root, node_id)
        except NotFoundError:
            return {
                **selection,
                "document": document,
                "node_id": node_id,
                "identity_status": "invalid",
                "reason": "deleted_or_absent",
                "identity": identity_contract(),
            }
        parent_id, position = self._parent_location(root, node_id)
        return {
            **selection,
            "document": document,
            "node_id": node_id,
            "identity_status": "present",
            "kind": node.get("kind"),
            "head": head_symbol(node),
            "name": declaration_name(node),
            "parent_id": parent_id,
            "position": position,
            "identity": identity_contract(),
        }

    def _resolve(
        self,
        root: JsonObject,
        *,
        node_id: str | None,
        kind: str | None,
        name: str | None,
    ) -> dict[str, Any]:
        if node_id is not None:
            if kind is not None or name is not None:
                raise ValidationError(
                    "INVALID_ENTITY_QUERY",
                    "node_id cannot be combined with kind or name lookup",
                    node_id=node_id,
                )
            try:
                node = find_node(root, node_id)
            except NotFoundError as exc:
                raise ValidationError(
                    "MISSING_STRUCTURAL_TARGET",
                    f"node {node_id!r} does not exist in this revision",
                    node_id=node_id,
                ) from exc
            return {
                "node_id": node["id"],
                "kind": head_symbol(node),
                "name": declaration_name(node),
            }

        if name is None:
            raise ValidationError(
                "INVALID_ENTITY_QUERY",
                "entity inspection requires node_id or a name",
            )
        matches = []
        for node in walk_nodes(root):
            form = head_symbol(node)
            if form is None or form not in DECLARATION_HEADS:
                continue
            if kind is not None and form != kind:
                continue
            if declaration_name(node) != name:
                continue
            matches.append(
                {
                    "node_id": node["id"],
                    "kind": form,
                    "name": name,
                }
            )
        if not matches:
            raise ValidationError(
                "MISSING_STRUCTURAL_TARGET",
                f"no declaration named {name!r} in this revision",
            )
        if len(matches) > 1:
            raise ValidationError(
                "AMBIGUOUS_TARGET",
                f"declaration {name!r} matches {len(matches)} nodes",
                matches=matches,
            )
        return matches[0]

    def _document(
        self,
        project: str,
        branch: str,
        document: str,
        revision_id: str | None,
    ) -> tuple[dict[str, Any], JsonObject]:
        branch_head = self.workspace.branch_head(project, branch)
        selected_revision = revision_id or branch_head
        if revision_id is not None:
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

    @staticmethod
    def _parent_location(
        root: JsonObject,
        node_id: str,
    ) -> tuple[str | None, int | None]:
        try:
            parent, index = find_parent(root, node_id)
        except NotFoundError:
            return None, None
        return str(parent["id"]), index

    @staticmethod
    def _signature(node: JsonObject) -> dict[str, Any]:
        children = node.get("children") if node.get("kind") == "list" else None
        params = None
        returns = None
        if isinstance(children, list):
            for child in children:
                form = head_symbol(child)
                if form == "params":
                    params = render_node(child)
                elif form == "returns":
                    returns = render_node(child)
        return {
            "head": head_symbol(node),
            "name": declaration_name(node),
            "params": params,
            "returns": returns,
        }

    @staticmethod
    def _truncate(node: JsonObject, depth: int) -> JsonObject:
        if depth <= 0 or node.get("kind") != "list":
            clipped = dict(node)
            if node.get("kind") == "list":
                clipped["children"] = []
            return clipped
        children = []
        for child in node.get("children") or []:
            children.append(EntityCatalogService._truncate(child, depth - 1))
        clipped = dict(node)
        clipped["children"] = children
        return clipped
