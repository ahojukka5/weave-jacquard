"""Atomic S-expression editing built on the versioned workspace service."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any
from uuid import uuid4

from .errors import ConflictError, NotFoundError, ValidationError
from .grammar_help import GrammarIndex
from .service import Workspace
from .sexpr import (
    ATOM_KINDS,
    JsonObject,
    find_node,
    find_parent,
    head_symbol,
    make_atom,
    make_form,
    parse_source,
    render_node,
    validate_tree,
    walk_nodes,
)
from .weavec import WeavecValidator


class SExpressionWorkspace(Workspace):
    """Grammar-neutral program tree with immutable history and stable node IDs."""

    def __init__(
        self,
        path: str | Path,
        *,
        weavec_source_root: str | Path | None = None,
        weavec_binary: str | Path | None = None,
    ) -> None:
        super().__init__(path)
        self.grammar = GrammarIndex(weavec_source_root)
        self.validator = WeavecValidator(weavec_binary, self.grammar.source_root)

    def list_branches(self, project: str) -> list[dict[str, str]]:
        rows = self.db.connection.execute(
            """SELECT b.name, b.head_revision_id
               FROM branches b JOIN projects p ON p.id = b.project_id
               WHERE p.name = ? ORDER BY b.name""",
            (project,),
        ).fetchall()
        return [dict(row) for row in rows]

    def create_program(
        self,
        project: str,
        branch: str,
        document: str,
        *,
        program_name: str,
        version: str = "0.1",
        author: str = "agent",
    ) -> dict[str, Any]:
        state = self._state(project, branch)
        if document in state:
            raise ValidationError(
                "DUPLICATE_DOCUMENT",
                f"document {document!r} already exists",
            )
        root = make_form("program")
        name_form = make_form("name")
        name_form["children"].append(make_atom("string", program_name))
        version_form = make_form("version")
        version_form["children"].append(make_atom("string", version))
        root["children"].extend([name_form, version_form])
        validate_tree(root)
        state[document] = root
        revision = self._commit(
            project,
            branch,
            state,
            message=f"create program {document}",
            author=author,
            operations=[("create_program", root["id"], {"document": document})],
        )
        return self._mutation_result(revision, branch, document, root, [root["id"]])

    def import_program(
        self,
        project: str,
        branch: str,
        document: str,
        source: str,
        *,
        replace: bool = False,
        author: str = "agent",
    ) -> dict[str, Any]:
        root = parse_source(source)
        state = self._state(project, branch)
        if document in state and not replace:
            raise ValidationError(
                "DUPLICATE_DOCUMENT",
                f"document {document!r} already exists",
            )
        state[document] = root
        revision = self._commit(
            project,
            branch,
            state,
            message=f"{'replace' if replace else 'import'} program {document}",
            author=author,
            operations=[("import_program", root["id"], {"document": document})],
        )
        return self._mutation_result(revision, branch, document, root, [root["id"]])

    def list_documents(
        self,
        project: str,
        branch: str = "main",
    ) -> list[dict[str, Any]]:
        return [
            {
                "document": name,
                "root_node_id": root["id"],
                "head": head_symbol(root),
                "node_count": sum(1 for _ in walk_nodes(root)),
            }
            for name, root in sorted(self._state(project, branch).items())
        ]

    def create_form(
        self,
        project: str,
        branch: str,
        document: str,
        parent_id: str,
        head: str,
        *,
        position: int | None = None,
        author: str = "agent",
    ) -> dict[str, Any]:
        state = self._state(project, branch)
        root = self._document(state, document)
        parent = find_node(root, parent_id)
        self._require_list(parent)
        form = make_form(head)
        index = self._insert_child(parent, form, position)
        revision = self._commit_tree_mutation(
            project,
            branch,
            state,
            root,
            message=f"add {head} form",
            author=author,
            operation=(
                "create_form",
                parent_id,
                {"node_id": form["id"], "head": head, "position": index},
            ),
        )
        result = self._mutation_result(revision, branch, document, form, [form["id"]])
        result.update(
            {
                "parent_id": parent_id,
                "position": index,
                "grammar_hint": self.grammar.hint_for_node(form),
            }
        )
        return result

    def add_atom(
        self,
        project: str,
        branch: str,
        document: str,
        parent_id: str,
        kind: str,
        value: Any,
        *,
        position: int | None = None,
        author: str = "agent",
    ) -> dict[str, Any]:
        if kind not in ATOM_KINDS:
            raise ValidationError(
                "INVALID_ATOM_KIND",
                f"atom kind must be one of {sorted(ATOM_KINDS)}",
            )
        state = self._state(project, branch)
        root = self._document(state, document)
        parent = find_node(root, parent_id)
        self._require_list(parent)
        atom = make_atom(kind, value)
        index = self._insert_child(parent, atom, position)
        revision = self._commit_tree_mutation(
            project,
            branch,
            state,
            root,
            message=f"add {kind} atom",
            author=author,
            operation=(
                "add_atom",
                parent_id,
                {"node_id": atom["id"], "kind": kind, "position": index},
            ),
        )
        result = self._mutation_result(revision, branch, document, atom, [atom["id"]])
        result.update(
            {
                "parent_id": parent_id,
                "position": index,
                "parent_grammar_hint": self.grammar.hint_for_node(parent),
            }
        )
        return result

    def set_atom(
        self,
        project: str,
        branch: str,
        document: str,
        node_id: str,
        value: Any,
        *,
        author: str = "agent",
    ) -> dict[str, Any]:
        state = self._state(project, branch)
        root = self._document(state, document)
        node = find_node(root, node_id)
        if node.get("kind") == "list":
            raise ValidationError(
                "NOT_ATOM",
                "set_atom requires an atom node",
                node_id=node_id,
            )
        old_value = node["value"]
        replacement = make_atom(node["kind"], value, node_id=node_id)
        node.clear()
        node.update(replacement)
        revision = self._commit_tree_mutation(
            project,
            branch,
            state,
            root,
            message=f"update atom {node_id}",
            author=author,
            operation=("set_atom", node_id, {"old": old_value, "new": value}),
        )
        return self._mutation_result(revision, branch, document, node, [])

    def delete_node(
        self,
        project: str,
        branch: str,
        document: str,
        node_id: str,
        *,
        author: str = "agent",
    ) -> dict[str, Any]:
        state = self._state(project, branch)
        root = self._document(state, document)
        if root["id"] == node_id:
            raise ValidationError(
                "DELETE_ROOT",
                "delete the document instead of its root node",
            )
        parent, index = find_parent(root, node_id)
        removed = parent["children"].pop(index)
        revision = self._commit_tree_mutation(
            project,
            branch,
            state,
            root,
            message=f"delete node {node_id}",
            author=author,
            operation=(
                "delete_node",
                node_id,
                {"parent_id": parent["id"], "position": index},
            ),
        )
        return {
            "revision_id": revision,
            "branch": branch,
            "document": document,
            "deleted_node_id": node_id,
            "deleted_head": head_symbol(removed),
            "parent_id": parent["id"],
        }

    def move_node(
        self,
        project: str,
        branch: str,
        document: str,
        node_id: str,
        new_parent_id: str,
        *,
        position: int | None = None,
        author: str = "agent",
    ) -> dict[str, Any]:
        state = self._state(project, branch)
        root = self._document(state, document)
        if root["id"] == node_id:
            raise ValidationError("MOVE_ROOT", "the document root cannot be moved")
        node = find_node(root, node_id)
        if any(descendant["id"] == new_parent_id for descendant in walk_nodes(node)):
            raise ValidationError(
                "MOVE_CYCLE",
                "cannot move a node inside its own subtree",
            )
        old_parent, old_index = find_parent(root, node_id)
        new_parent = find_node(root, new_parent_id)
        self._require_list(new_parent)
        old_parent["children"].pop(old_index)
        index = self._insert_child(new_parent, node, position)
        revision = self._commit_tree_mutation(
            project,
            branch,
            state,
            root,
            message=f"move node {node_id}",
            author=author,
            operation=(
                "move_node",
                node_id,
                {
                    "old_parent_id": old_parent["id"],
                    "old_position": old_index,
                    "new_parent_id": new_parent_id,
                    "new_position": index,
                },
            ),
        )
        return self._mutation_result(revision, branch, document, node, [])

    def wrap_node(
        self,
        project: str,
        branch: str,
        document: str,
        node_id: str,
        head: str,
        *,
        author: str = "agent",
    ) -> dict[str, Any]:
        state = self._state(project, branch)
        root = self._document(state, document)
        if root["id"] == node_id:
            raise ValidationError(
                "WRAP_ROOT",
                "the document root cannot be wrapped in place",
            )
        parent, index = find_parent(root, node_id)
        wrapper = make_form(head)
        wrapper["children"].append(parent["children"][index])
        parent["children"][index] = wrapper
        revision = self._commit_tree_mutation(
            project,
            branch,
            state,
            root,
            message=f"wrap node {node_id} with {head}",
            author=author,
            operation=(
                "wrap_node",
                node_id,
                {"wrapper_id": wrapper["id"], "head": head},
            ),
        )
        result = self._mutation_result(
            revision,
            branch,
            document,
            wrapper,
            [wrapper["id"]],
        )
        result.update(
            {
                "wrapped_node_id": node_id,
                "grammar_hint": self.grammar.hint_for_node(wrapper),
            }
        )
        return result

    def inspect_node(
        self,
        project: str,
        branch: str,
        document: str,
        node_id: str,
        *,
        depth: int = 3,
    ) -> dict[str, Any]:
        root = self._document(self._state(project, branch), document)
        node = find_node(root, node_id)
        try:
            parent, index = find_parent(root, node_id)
            parent_id: str | None = parent["id"]
        except NotFoundError:
            parent_id = None
            index = 0
        subtree = self._truncate(node, max(0, depth))
        return {
            "document": document,
            "branch": branch,
            "node_id": node_id,
            "kind": node["kind"],
            "head": head_symbol(node),
            "parent_id": parent_id,
            "position": index if parent_id else None,
            "subtree": subtree,
            "annotated_weave": render_node(subtree, annotated=True),
            "grammar_hint": self.grammar.hint_for_node(node),
        }

    def find_nodes(
        self,
        project: str,
        branch: str,
        document: str,
        *,
        head: str | None = None,
        kind: str | None = None,
        value: Any | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        root = self._document(self._state(project, branch), document)
        result: list[dict[str, Any]] = []
        for node in walk_nodes(root):
            if head is not None and head_symbol(node) != head:
                continue
            if kind is not None and node.get("kind") != kind:
                continue
            if value is not None and node.get("value") != value:
                continue
            try:
                parent, index = find_parent(root, node["id"])
                parent_id = parent["id"]
            except NotFoundError:
                parent_id = None
                index = None
            result.append(
                {
                    "node_id": node["id"],
                    "kind": node["kind"],
                    "head": head_symbol(node),
                    "value": node.get("value"),
                    "parent_id": parent_id,
                    "position": index,
                }
            )
            if len(result) >= limit:
                break
        return result

    def render(
        self,
        project: str,
        branch: str,
        document: str,
        *,
        annotated: bool = False,
        annotate_atoms: bool = False,
    ) -> str:
        root = self._document(self._state(project, branch), document)
        return render_node(
            root,
            annotated=annotated,
            annotate_atoms=annotate_atoms,
        )

    def validate_program(
        self,
        project: str,
        branch: str,
        document: str,
    ) -> dict[str, Any]:
        root = self._document(self._state(project, branch), document)
        validate_tree(root)
        result = self.validator.validate(render_node(root))
        result.update(
            {
                "structurally_valid": True,
                "document": document,
                "root_node_id": root["id"],
                "revision_id": self.branch_head(project, branch),
            }
        )
        return result

    def add_context(
        self,
        project: str,
        branch: str,
        *,
        scope_kind: str,
        scope_name: str,
        title: str,
        body: str,
        author: str = "agent",
    ) -> dict[str, Any]:
        if scope_kind not in {"project", "document", "symbol"}:
            raise ValidationError(
                "INVALID_SCOPE",
                "scope_kind must be project, document, or symbol",
            )
        state = self._state(project, branch)
        content_hash = self.db.hash_value(
            {
                "scope_kind": scope_kind,
                "scope_name": scope_name,
                "title": title,
                "body": body,
            }
        )
        document_id = str(uuid4())
        with self.db.transaction() as conn:
            existing = conn.execute(
                "SELECT id FROM documents WHERE content_hash = ?",
                (content_hash,),
            ).fetchone()
            if existing is not None:
                document_id = str(existing["id"])
            else:
                conn.execute(
                    """INSERT INTO documents(
                           id, scope_kind, scope_name, title, body, content_hash
                       ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        document_id,
                        scope_kind,
                        scope_name,
                        title,
                        body,
                        content_hash,
                    ),
                )
        revision = self._commit(
            project,
            branch,
            state,
            message=f"add context {title}",
            author=author,
            operations=[
                ("add_context", scope_name, {"document_id": document_id})
            ],
            extra_document_ids=[document_id],
        )
        return {
            "revision_id": revision,
            "branch": branch,
            "document_id": document_id,
        }

    def get_context(
        self,
        project: str,
        branch: str,
        *,
        scope_name: str,
    ) -> list[dict[str, Any]]:
        revision = self.branch_head(project, branch)
        rows = self.db.connection.execute(
            """SELECT d.id, d.scope_kind, d.scope_name, d.title, d.body,
                      d.content_hash
               FROM revision_documents rd
               JOIN documents d ON d.id = rd.document_id
               WHERE rd.revision_id = ?
                 AND ((d.scope_kind = 'project' AND d.scope_name = ?)
                   OR d.scope_name = ?)
               ORDER BY d.scope_kind, d.title""",
            (revision, project, scope_name),
        ).fetchall()
        return [dict(row) for row in rows]

    def grammar_help(
        self,
        *,
        form: str | None = None,
        query: str | None = None,
        parent_form: str | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        return self.grammar.help(
            form=form,
            query=query,
            parent_form=parent_form,
            limit=limit,
        )

    @staticmethod
    def _document(
        state: dict[str, JsonObject],
        document: str,
    ) -> JsonObject:
        try:
            return state[document]
        except KeyError as exc:
            raise NotFoundError(f"document {document!r} not found") from exc

    @staticmethod
    def _require_list(node: JsonObject) -> None:
        if node.get("kind") != "list":
            raise ValidationError(
                "NOT_LIST",
                "operation requires a list node",
                node_id=node.get("id"),
            )

    @staticmethod
    def _insert_child(
        parent: JsonObject,
        child: JsonObject,
        position: int | None,
    ) -> int:
        children = parent["children"]
        index = len(children) if position is None else position
        if index < 0 or index > len(children):
            raise ValidationError(
                "INVALID_POSITION",
                f"position {index} is outside the child list",
            )
        children.insert(index, child)
        return index

    def _commit_tree_mutation(
        self,
        project: str,
        branch: str,
        state: dict[str, JsonObject],
        root: JsonObject,
        *,
        message: str,
        author: str,
        operation: tuple[str, str | None, JsonObject],
    ) -> str:
        validate_tree(root)
        return self._commit(
            project,
            branch,
            state,
            message=message,
            author=author,
            operations=[operation],
        )

    @staticmethod
    def _mutation_result(
        revision: str,
        branch: str,
        document: str,
        node: JsonObject,
        created: list[str],
    ) -> dict[str, Any]:
        return {
            "revision_id": revision,
            "branch": branch,
            "document": document,
            "node_id": node["id"],
            "created_node_ids": created,
            "kind": node["kind"],
            "head": head_symbol(node),
            "annotated_weave": render_node(node, annotated=True),
        }

    @classmethod
    def _truncate(cls, node: JsonObject, depth: int) -> JsonObject:
        if node.get("kind") != "list":
            return copy.deepcopy(node)
        if depth <= 0:
            return {
                "id": node["id"],
                "kind": "list",
                "children": [],
                "truncated_child_count": len(node["children"]),
            }
        return {
            "id": node["id"],
            "kind": "list",
            "children": [
                cls._truncate(child, depth - 1)
                for child in node["children"]
            ],
        }

    @classmethod
    def _validate_state(cls, state: dict[str, JsonObject]) -> None:
        for root in state.values():
            validate_tree(root)

    @classmethod
    def _merge_states(
        cls,
        base: dict[str, JsonObject],
        ours: dict[str, JsonObject],
        theirs: dict[str, JsonObject],
    ) -> tuple[dict[str, JsonObject], set[str]]:
        merged: dict[str, JsonObject] = {}
        conflicts: list[str] = []
        changed: set[str] = set()
        for name in sorted(set(base) | set(ours) | set(theirs)):
            value = cls._merge_node(
                base.get(name),
                ours.get(name),
                theirs.get(name),
                conflicts,
                path=f"document:{name}",
            )
            if value is not None:
                merged[name] = value
            if value != ours.get(name):
                changed.add(name)
        if conflicts:
            raise ConflictError(conflicts)
        return merged, changed

    @classmethod
    def _merge_node(
        cls,
        base: JsonObject | None,
        ours: JsonObject | None,
        theirs: JsonObject | None,
        conflicts: list[str],
        *,
        path: str,
    ) -> JsonObject | None:
        if ours == base:
            return copy.deepcopy(theirs)
        if theirs == base or ours == theirs:
            return copy.deepcopy(ours)
        if base is None:
            if ours is None:
                return copy.deepcopy(theirs)
            if theirs is None:
                return copy.deepcopy(ours)
            conflicts.append(path)
            return copy.deepcopy(ours)
        if ours is None or theirs is None:
            conflicts.append(path)
            return copy.deepcopy(ours if ours is not None else theirs)
        if ours.get("id") != base.get("id") or theirs.get("id") != base.get("id"):
            conflicts.append(path)
            return copy.deepcopy(ours)
        if ours.get("kind") != base.get("kind") or theirs.get("kind") != base.get("kind"):
            conflicts.append(f"{path}:{base['id']}:kind")
            return copy.deepcopy(ours)
        if base["kind"] != "list":
            conflicts.append(f"{path}:{base['id']}:value")
            return copy.deepcopy(ours)
        return {
            "id": base["id"],
            "kind": "list",
            "children": cls._merge_children(
                base,
                ours,
                theirs,
                conflicts,
                path=path,
            ),
        }

    @classmethod
    def _merge_children(
        cls,
        base: JsonObject,
        ours: JsonObject,
        theirs: JsonObject,
        conflicts: list[str],
        *,
        path: str,
    ) -> list[JsonObject]:
        base_children = base["children"]
        our_children = ours["children"]
        their_children = theirs["children"]
        base_ids = [child["id"] for child in base_children]
        base_set = set(base_ids)
        cls._check_base_order(base_ids, our_children, conflicts, path, base["id"])
        cls._check_base_order(base_ids, their_children, conflicts, path, base["id"])

        base_map = {child["id"]: child for child in base_children}
        our_map = {child["id"]: child for child in our_children}
        their_map = {child["id"]: child for child in their_children}
        our_additions = cls._addition_slots(our_children, base_set)
        their_additions = cls._addition_slots(their_children, base_set)

        result = cls._merge_additions(
            our_additions.get(None, []),
            their_additions.get(None, []),
        )
        for child_id in base_ids:
            merged_child = cls._merge_node(
                base_map[child_id],
                our_map.get(child_id),
                their_map.get(child_id),
                conflicts,
                path=f"{path}/{child_id}",
            )
            if merged_child is not None:
                result.append(merged_child)
            result.extend(
                cls._merge_additions(
                    our_additions.get(child_id, []),
                    their_additions.get(child_id, []),
                )
            )
        return result

    @staticmethod
    def _check_base_order(
        base_ids: list[str],
        children: list[JsonObject],
        conflicts: list[str],
        path: str,
        node_id: str,
    ) -> None:
        base_set = set(base_ids)
        actual = [child["id"] for child in children if child["id"] in base_set]
        expected = [child_id for child_id in base_ids if child_id in set(actual)]
        if actual != expected:
            conflicts.append(f"{path}:{node_id}:reorder")

    @staticmethod
    def _addition_slots(
        children: list[JsonObject],
        base_ids: set[str],
    ) -> dict[str | None, list[JsonObject]]:
        slots: dict[str | None, list[JsonObject]] = {}
        anchor: str | None = None
        for child in children:
            child_id = child["id"]
            if child_id in base_ids:
                anchor = child_id
            else:
                slots.setdefault(anchor, []).append(child)
        return slots

    @staticmethod
    def _merge_additions(
        ours: list[JsonObject],
        theirs: list[JsonObject],
    ) -> list[JsonObject]:
        result: list[JsonObject] = []
        seen: set[str] = set()
        for child in [*ours, *theirs]:
            if child["id"] in seen:
                continue
            seen.add(child["id"])
            result.append(copy.deepcopy(child))
        return result
