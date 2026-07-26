"""Race-safe public S-expression node mutations."""

from __future__ import annotations

from typing import Any

from .errors import ValidationError
from .sexpr import (
    ATOM_KINDS,
    JsonObject,
    find_node,
    find_parent,
    head_symbol,
    make_atom,
    make_form,
    validate_tree,
    walk_nodes,
)
from .sexpr_service import SExpressionWorkspace as _BaseSExpressionWorkspace


class SExpressionWorkspace(_BaseSExpressionWorkspace):
    """Public workspace whose single-node writes use branch compare-and-set."""

    def create_form(
        self,
        project: str,
        branch: str,
        document: str,
        parent_id: str,
        head: str,
        *,
        position: int | None = None,
        expected_revision_id: str | None = None,
        author: str = "agent",
    ) -> dict[str, Any]:
        base_revision_id, state = self._state_for_write(
            project,
            branch,
            expected_revision_id=expected_revision_id,
        )
        root = self._document(state, document)
        parent = find_node(root, parent_id)
        self._require_list(parent)
        form = make_form(head)
        index = self._insert_child(parent, form, position)
        revision = self._commit_node_mutation(
            project,
            branch,
            base_revision_id,
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
                "base_revision_id": base_revision_id,
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
        expected_revision_id: str | None = None,
        author: str = "agent",
    ) -> dict[str, Any]:
        if kind not in ATOM_KINDS:
            raise ValidationError(
                "INVALID_ATOM_KIND",
                f"atom kind must be one of {sorted(ATOM_KINDS)}",
            )
        base_revision_id, state = self._state_for_write(
            project,
            branch,
            expected_revision_id=expected_revision_id,
        )
        root = self._document(state, document)
        parent = find_node(root, parent_id)
        self._require_list(parent)
        atom = make_atom(kind, value)
        index = self._insert_child(parent, atom, position)
        revision = self._commit_node_mutation(
            project,
            branch,
            base_revision_id,
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
                "base_revision_id": base_revision_id,
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
        expected_revision_id: str | None = None,
        author: str = "agent",
    ) -> dict[str, Any]:
        base_revision_id, state = self._state_for_write(
            project,
            branch,
            expected_revision_id=expected_revision_id,
        )
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
        revision = self._commit_node_mutation(
            project,
            branch,
            base_revision_id,
            state,
            root,
            message=f"update atom {node_id}",
            author=author,
            operation=("set_atom", node_id, {"old": old_value, "new": value}),
        )
        result = self._mutation_result(revision, branch, document, node, [])
        result["base_revision_id"] = base_revision_id
        return result

    def delete_node(
        self,
        project: str,
        branch: str,
        document: str,
        node_id: str,
        *,
        expected_revision_id: str | None = None,
        author: str = "agent",
    ) -> dict[str, Any]:
        base_revision_id, state = self._state_for_write(
            project,
            branch,
            expected_revision_id=expected_revision_id,
        )
        root = self._document(state, document)
        if root["id"] == node_id:
            raise ValidationError(
                "DELETE_ROOT",
                "delete the document instead of its root node",
            )
        parent, index = find_parent(root, node_id)
        removed = parent["children"].pop(index)
        revision = self._commit_node_mutation(
            project,
            branch,
            base_revision_id,
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
            "base_revision_id": base_revision_id,
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
        expected_revision_id: str | None = None,
        author: str = "agent",
    ) -> dict[str, Any]:
        base_revision_id, state = self._state_for_write(
            project,
            branch,
            expected_revision_id=expected_revision_id,
        )
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
        revision = self._commit_node_mutation(
            project,
            branch,
            base_revision_id,
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
        result = self._mutation_result(revision, branch, document, node, [])
        result["base_revision_id"] = base_revision_id
        return result

    def wrap_node(
        self,
        project: str,
        branch: str,
        document: str,
        node_id: str,
        head: str,
        *,
        expected_revision_id: str | None = None,
        author: str = "agent",
    ) -> dict[str, Any]:
        base_revision_id, state = self._state_for_write(
            project,
            branch,
            expected_revision_id=expected_revision_id,
        )
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
        revision = self._commit_node_mutation(
            project,
            branch,
            base_revision_id,
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
                "base_revision_id": base_revision_id,
                "wrapped_node_id": node_id,
                "grammar_hint": self.grammar.hint_for_node(wrapper),
            }
        )
        return result

    def _commit_node_mutation(
        self,
        project: str,
        branch: str,
        base_revision_id: str,
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
            expected_branch_heads={branch: base_revision_id},
            stale_error_code="STALE_BRANCH_HEAD",
        )
