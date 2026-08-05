"""Bounded transactional structural edits for agent workflows."""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from .errors import NotFoundError, ValidationError
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
from .sexpr_service import SExpressionWorkspace

MAX_BATCH_OPERATIONS = 256
_ALIAS_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")


class BatchOperationError(ValidationError):
    """Validation failure tied to one operation in a structural batch."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        operation_index: int,
        operation: str | None,
        node_id: str | None = None,
    ) -> None:
        super().__init__(code, message, node_id=node_id)
        self.operation_index = operation_index
        self.operation = operation

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = super().as_dict()
        result.update(
            {
                "operation_index": self.operation_index,
                "operation": self.operation,
            }
        )
        return result


class EditBatchExecutor:
    """Apply a bounded flat operation list as one immutable revision."""

    def __init__(self, workspace: SExpressionWorkspace) -> None:
        self.workspace = workspace

    def apply(
        self,
        project: str,
        branch: str,
        document: str,
        operations: list[dict[str, Any]],
        *,
        expected_revision_id: str | None = None,
        message: str | None = None,
        author: str = "agent",
        include_operation_results: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(operations, list) or not operations:
            raise ValidationError(
                "EMPTY_EDIT_BATCH",
                "operations must contain at least one structural edit",
            )
        if len(operations) > MAX_BATCH_OPERATIONS:
            raise ValidationError(
                "EDIT_BATCH_TOO_LARGE",
                f"at most {MAX_BATCH_OPERATIONS} operations are allowed per batch",
            )

        base_revision_id = self.workspace.branch_head(project, branch)
        if expected_revision_id is not None and expected_revision_id != base_revision_id:
            raise ValidationError(
                "STALE_REVISION",
                "branch head does not match expected_revision_id",
            )

        state = self.workspace._state_at_revision(base_revision_id)
        root = self.workspace._document(state, document)
        aliases: dict[str, str] = {}
        operation_log: list[tuple[str, str | None, JsonObject]] = []
        operation_results: list[dict[str, Any]] = []
        created_count = 0
        deleted_count = 0

        for index, raw in enumerate(operations):
            operation_name = raw.get("op") if isinstance(raw, dict) else None
            try:
                result, log_entry, created, deleted = self._apply_one(
                    root,
                    raw,
                    aliases,
                    index=index,
                )
            except BatchOperationError:
                raise
            except ValidationError as exc:
                raise BatchOperationError(
                    exc.code,
                    exc.message,
                    operation_index=index,
                    operation=(operation_name if isinstance(operation_name, str) else None),
                    node_id=exc.node_id,
                ) from exc
            except NotFoundError as exc:
                raise BatchOperationError(
                    "NOT_FOUND",
                    str(exc),
                    operation_index=index,
                    operation=(operation_name if isinstance(operation_name, str) else None),
                ) from exc
            operation_log.append(log_entry)
            operation_results.append(result)
            created_count += created
            deleted_count += deleted

        validate_tree(root)
        self.workspace._validate_state(state)
        revision_id = self._commit_if_head(
            project,
            branch,
            state,
            base_revision_id=base_revision_id,
            message=message or f"apply {len(operations)} structural edits",
            author=author,
            operations=operation_log,
        )
        response: dict[str, Any] = {
            "revision_id": revision_id,
            "base_revision_id": base_revision_id,
            "branch": branch,
            "document": document,
            "root_node_id": root["id"],
            "operation_count": len(operations),
            "created_node_count": created_count,
            "deleted_node_count": deleted_count,
            "node_count": sum(1 for _ in walk_nodes(root)),
            "aliases": dict(sorted(aliases.items())),
        }
        if include_operation_results:
            response["operation_results"] = operation_results
        return response

    def _apply_one(
        self,
        root: JsonObject,
        raw: dict[str, Any],
        aliases: dict[str, str],
        *,
        index: int,
    ) -> tuple[dict[str, Any], tuple[str, str | None, JsonObject], int, int]:
        if not isinstance(raw, dict):
            raise BatchOperationError(
                "INVALID_BATCH_OPERATION",
                "each operation must be an object",
                operation_index=index,
                operation=None,
            )
        operation = raw.get("op")
        if not isinstance(operation, str):
            raise BatchOperationError(
                "INVALID_BATCH_OPERATION",
                "operation requires a string op field",
                operation_index=index,
                operation=None,
            )
        handlers = {
            "create_form": self._create_form,
            "add_atom": self._add_atom,
            "set_atom": self._set_atom,
            "move_node": self._move_node,
            "wrap_node": self._wrap_node,
            "delete_node": self._delete_node,
        }
        try:
            handler = handlers[operation]
        except KeyError as exc:
            raise BatchOperationError(
                "UNKNOWN_BATCH_OPERATION",
                f"unsupported batch operation {operation!r}",
                operation_index=index,
                operation=operation,
            ) from exc
        return handler(root, raw, aliases, index=index)

    def _create_form(
        self,
        root: JsonObject,
        raw: dict[str, Any],
        aliases: dict[str, str],
        *,
        index: int,
    ) -> tuple[dict[str, Any], tuple[str, str | None, JsonObject], int, int]:
        self._reject_unknown(raw, {"op", "parent", "head", "position", "as"})
        parent_id = self._resolve_reference(raw.get("parent"), aliases)
        head = self._required_string(raw, "head")
        parent = find_node(root, parent_id)
        self._require_list(parent)
        node = make_form(head)
        position = self._insert_child(parent, node, raw.get("position"))
        alias = self._register_alias(raw.get("as"), node["id"], aliases)
        payload: JsonObject = {
            "node_id": node["id"],
            "head": head,
            "position": position,
            "batch_index": index,
        }
        return (
            {
                "op": "create_form",
                "node_id": node["id"],
                "parent_id": parent_id,
                "position": position,
                "head": head,
                "alias": alias,
            },
            ("create_form", parent_id, payload),
            1,
            0,
        )

    def _add_atom(
        self,
        root: JsonObject,
        raw: dict[str, Any],
        aliases: dict[str, str],
        *,
        index: int,
    ) -> tuple[dict[str, Any], tuple[str, str | None, JsonObject], int, int]:
        self._reject_unknown(
            raw,
            {"op", "parent", "kind", "value", "position", "as"},
        )
        parent_id = self._resolve_reference(raw.get("parent"), aliases)
        kind = self._required_string(raw, "kind")
        if kind not in ATOM_KINDS:
            raise ValidationError(
                "INVALID_ATOM_KIND",
                f"atom kind must be one of {sorted(ATOM_KINDS)}",
            )
        if "value" not in raw:
            raise ValidationError("MISSING_VALUE", "add_atom requires value")
        parent = find_node(root, parent_id)
        self._require_list(parent)
        node = make_atom(kind, raw["value"])
        position = self._insert_child(parent, node, raw.get("position"))
        alias = self._register_alias(raw.get("as"), node["id"], aliases)
        payload: JsonObject = {
            "node_id": node["id"],
            "kind": kind,
            "position": position,
            "batch_index": index,
        }
        return (
            {
                "op": "add_atom",
                "node_id": node["id"],
                "parent_id": parent_id,
                "position": position,
                "kind": kind,
                "alias": alias,
            },
            ("add_atom", parent_id, payload),
            1,
            0,
        )

    def _set_atom(
        self,
        root: JsonObject,
        raw: dict[str, Any],
        aliases: dict[str, str],
        *,
        index: int,
    ) -> tuple[dict[str, Any], tuple[str, str | None, JsonObject], int, int]:
        self._reject_unknown(raw, {"op", "node", "value"})
        node_id = self._resolve_reference(raw.get("node"), aliases)
        if "value" not in raw:
            raise ValidationError("MISSING_VALUE", "set_atom requires value")
        node = find_node(root, node_id)
        if node.get("kind") == "list":
            raise ValidationError(
                "NOT_ATOM",
                "set_atom requires an atom node",
                node_id=node_id,
            )
        old_value = node["value"]
        replacement = make_atom(node["kind"], raw["value"], node_id=node_id)
        node.clear()
        node.update(replacement)
        payload: JsonObject = {
            "old": old_value,
            "new": raw["value"],
            "batch_index": index,
        }
        return (
            {
                "op": "set_atom",
                "node_id": node_id,
                "old_value": old_value,
                "new_value": raw["value"],
            },
            ("set_atom", node_id, payload),
            0,
            0,
        )

    def _move_node(
        self,
        root: JsonObject,
        raw: dict[str, Any],
        aliases: dict[str, str],
        *,
        index: int,
    ) -> tuple[dict[str, Any], tuple[str, str | None, JsonObject], int, int]:
        self._reject_unknown(raw, {"op", "node", "new_parent", "position"})
        node_id = self._resolve_reference(raw.get("node"), aliases)
        new_parent_id = self._resolve_reference(raw.get("new_parent"), aliases)
        if root["id"] == node_id:
            raise ValidationError("MOVE_ROOT", "the document root cannot be moved")
        node = find_node(root, node_id)
        if any(descendant["id"] == new_parent_id for descendant in walk_nodes(node)):
            raise ValidationError(
                "MOVE_CYCLE",
                "cannot move a node inside its own subtree",
                node_id=node_id,
            )
        old_parent, old_position = find_parent(root, node_id)
        new_parent = find_node(root, new_parent_id)
        self._require_list(new_parent)
        old_parent["children"].pop(old_position)
        new_position = self._insert_child(new_parent, node, raw.get("position"))
        payload: JsonObject = {
            "old_parent_id": old_parent["id"],
            "old_position": old_position,
            "new_parent_id": new_parent_id,
            "new_position": new_position,
            "batch_index": index,
        }
        return (
            {
                "op": "move_node",
                "node_id": node_id,
                "old_parent_id": old_parent["id"],
                "old_position": old_position,
                "new_parent_id": new_parent_id,
                "new_position": new_position,
            },
            ("move_node", node_id, payload),
            0,
            0,
        )

    def _wrap_node(
        self,
        root: JsonObject,
        raw: dict[str, Any],
        aliases: dict[str, str],
        *,
        index: int,
    ) -> tuple[dict[str, Any], tuple[str, str | None, JsonObject], int, int]:
        self._reject_unknown(raw, {"op", "node", "head", "as"})
        node_id = self._resolve_reference(raw.get("node"), aliases)
        head = self._required_string(raw, "head")
        if root["id"] == node_id:
            raise ValidationError(
                "WRAP_ROOT",
                "the document root cannot be wrapped in place",
            )
        parent, position = find_parent(root, node_id)
        wrapper = make_form(head)
        wrapper["children"].append(parent["children"][position])
        parent["children"][position] = wrapper
        alias = self._register_alias(raw.get("as"), wrapper["id"], aliases)
        payload: JsonObject = {
            "wrapper_id": wrapper["id"],
            "head": head,
            "batch_index": index,
        }
        return (
            {
                "op": "wrap_node",
                "node_id": node_id,
                "wrapper_id": wrapper["id"],
                "parent_id": parent["id"],
                "position": position,
                "head": head,
                "alias": alias,
            },
            ("wrap_node", node_id, payload),
            1,
            0,
        )

    def _delete_node(
        self,
        root: JsonObject,
        raw: dict[str, Any],
        aliases: dict[str, str],
        *,
        index: int,
    ) -> tuple[dict[str, Any], tuple[str, str | None, JsonObject], int, int]:
        self._reject_unknown(raw, {"op", "node"})
        node_id = self._resolve_reference(raw.get("node"), aliases)
        if root["id"] == node_id:
            raise ValidationError(
                "DELETE_ROOT",
                "delete the document instead of its root node",
            )
        parent, position = find_parent(root, node_id)
        removed = parent["children"].pop(position)
        removed_ids = {node["id"] for node in walk_nodes(removed)}
        invalidated = sorted(alias for alias, target in aliases.items() if target in removed_ids)
        for alias in invalidated:
            aliases.pop(alias)
        payload: JsonObject = {
            "parent_id": parent["id"],
            "position": position,
            "batch_index": index,
        }
        return (
            {
                "op": "delete_node",
                "deleted_node_id": node_id,
                "deleted_head": head_symbol(removed),
                "parent_id": parent["id"],
                "position": position,
                "invalidated_aliases": invalidated,
            },
            ("delete_node", node_id, payload),
            0,
            len(removed_ids),
        )

    def _commit_if_head(
        self,
        project: str,
        branch: str,
        modules: dict[str, JsonObject],
        *,
        base_revision_id: str,
        message: str,
        author: str,
        operations: list[tuple[str, str | None, JsonObject]],
    ) -> str:
        project_id = self.workspace.project_id(project)
        revision_id = str(uuid4())
        root_hash = self.workspace.db.hash_value(modules)
        with self.workspace.db.transaction() as connection:
            branch_row = connection.execute(
                """SELECT head_revision_id FROM branches
                   WHERE project_id = ? AND name = ?""",
                (project_id, branch),
            ).fetchone()
            if branch_row is None:
                raise NotFoundError(f"branch {branch!r} not found")
            if str(branch_row["head_revision_id"]) != base_revision_id:
                raise ValidationError(
                    "STALE_REVISION",
                    "branch head advanced while the edit batch was prepared",
                )
            parent_documents = connection.execute(
                "SELECT document_id FROM revision_documents WHERE revision_id = ?",
                (base_revision_id,),
            ).fetchall()
            connection.execute(
                """INSERT INTO revisions(
                       id, project_id, parent1_id, parent2_id, message, author, root_hash
                   ) VALUES (?, ?, ?, NULL, ?, ?, ?)""",
                (
                    revision_id,
                    project_id,
                    base_revision_id,
                    message,
                    author,
                    root_hash,
                ),
            )
            for module_name, ast in sorted(modules.items()):
                canonical = self.workspace.db.canonical_json(ast)
                connection.execute(
                    """INSERT INTO module_snapshots(
                           revision_id, qualified_name, ast_json, ast_hash
                       ) VALUES (?, ?, ?, ?)""",
                    (
                        revision_id,
                        module_name,
                        canonical,
                        self.workspace.db.hash_value(ast),
                    ),
                )
            for sequence, (kind, target, payload) in enumerate(operations):
                connection.execute(
                    """INSERT INTO operations(
                           id, revision_id, sequence_number, operation_kind,
                           target, payload_json
                       ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid4()),
                        revision_id,
                        sequence,
                        kind,
                        target,
                        self.workspace.db.canonical_json(payload),
                    ),
                )
            for row in parent_documents:
                connection.execute(
                    """INSERT INTO revision_documents(revision_id, document_id)
                       VALUES (?, ?)""",
                    (revision_id, str(row["document_id"])),
                )
            updated = connection.execute(
                """UPDATE branches SET head_revision_id = ?
                   WHERE project_id = ? AND name = ? AND head_revision_id = ?""",
                (revision_id, project_id, branch, base_revision_id),
            )
            if updated.rowcount != 1:
                raise ValidationError(
                    "STALE_REVISION",
                    "branch head advanced while the edit batch was committed",
                )
        return revision_id

    @staticmethod
    def _required_string(raw: dict[str, Any], name: str) -> str:
        value = raw.get(name)
        if not isinstance(value, str) or not value:
            raise ValidationError(
                "INVALID_BATCH_OPERATION",
                f"{name} must be a non-empty string",
            )
        return value

    @staticmethod
    def _resolve_reference(value: Any, aliases: dict[str, str]) -> str:
        if not isinstance(value, str) or not value:
            raise ValidationError(
                "INVALID_NODE_REFERENCE",
                "node references must be non-empty strings",
            )
        if not value.startswith("@"):
            return value
        alias = value[1:]
        try:
            return aliases[alias]
        except KeyError as exc:
            raise ValidationError(
                "UNKNOWN_BATCH_ALIAS",
                f"batch alias {alias!r} has not been defined",
            ) from exc

    @staticmethod
    def _register_alias(
        value: Any,
        node_id: str,
        aliases: dict[str, str],
    ) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not _ALIAS_PATTERN.fullmatch(value):
            raise ValidationError(
                "INVALID_BATCH_ALIAS",
                "aliases must start with a letter and contain at most 64 letters, "
                "digits, underscores, or hyphens",
            )
        if value in aliases:
            raise ValidationError(
                "DUPLICATE_BATCH_ALIAS",
                f"batch alias {value!r} is already defined",
            )
        aliases[value] = node_id
        return value

    @staticmethod
    def _reject_unknown(raw: dict[str, Any], allowed: set[str]) -> None:
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise ValidationError(
                "UNKNOWN_BATCH_FIELD",
                f"unsupported fields: {', '.join(unknown)}",
            )

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
        position: Any,
    ) -> int:
        children = parent["children"]
        if position is None:
            index = len(children)
        elif isinstance(position, int) and not isinstance(position, bool):
            index = position
        else:
            raise ValidationError(
                "INVALID_POSITION",
                "position must be an integer or null",
            )
        if index < 0 or index > len(children):
            raise ValidationError(
                "INVALID_POSITION",
                f"position {index} is outside the child list",
            )
        children.insert(index, child)
        return index
