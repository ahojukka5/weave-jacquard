"""High-level agent-facing workspace API.

Every mutation is checked before it becomes a new immutable revision. Branches
point to revision heads, so parallel agents can work independently and merge
at symbol granularity.
"""

from __future__ import annotations

import copy
import json
from collections import deque
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from uuid import uuid4

from .database import Database
from .errors import ConflictError, NotFoundError, ValidationError
from .grammar import (
    ensure_node_ids,
    validate_function_semantics,
    validate_function_shape,
    validate_statement_shape,
)
from .model import JsonObject, MergeResult, MutationResult, SymbolSummary
from .renderer import render_module


class Workspace:
    """Versioned Weave AST workspace backed by one SQLite database."""

    def __init__(self, path: str | Path) -> None:
        self.db = Database(path)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> Workspace:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def initialize(self, name: str, *, author: str = "system") -> tuple[str, str]:
        return self.db.initialize_project(name, author=author)

    def project_id(self, name: str) -> str:
        row = self.db.connection.execute(
            "SELECT id FROM projects WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"project {name!r} not found")
        return str(row["id"])

    def branch_head(self, project: str, branch: str = "main") -> str:
        project_id = self.project_id(project)
        row = self.db.connection.execute(
            "SELECT head_revision_id FROM branches WHERE project_id = ? AND name = ?",
            (project_id, branch),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"branch {branch!r} not found")
        return str(row["head_revision_id"])

    def create_branch(self, project: str, name: str, *, from_branch: str = "main") -> str:
        project_id = self.project_id(project)
        head = self.branch_head(project, from_branch)
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO branches(project_id, name, head_revision_id) VALUES (?, ?, ?)",
                (project_id, name, head),
            )
        return head

    def checkout(self, project: str, branch: str, revision_id: str) -> None:
        project_id = self.project_id(project)
        row = self.db.connection.execute(
            "SELECT 1 FROM revisions WHERE id = ? AND project_id = ?", (revision_id, project_id)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"revision {revision_id!r} not found")
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE branches SET head_revision_id = ? WHERE project_id = ? AND name = ?",
                (revision_id, project_id, branch),
            )

    def list_history(
        self, project: str, branch: str = "main", *, limit: int = 100
    ) -> list[JsonObject]:
        current = self.branch_head(project, branch)
        history: list[JsonObject] = []
        while current and len(history) < limit:
            row = self.db.connection.execute(
                """SELECT id, parent1_id, parent2_id, message, author, root_hash,
                          created_at
                   FROM revisions WHERE id = ?""",
                (current,),
            ).fetchone()
            if row is None:
                break
            history.append(dict(row))
            current = row["parent1_id"]
        return history

    def create_module(
        self,
        project: str,
        branch: str,
        qualified_name: str,
        *,
        author: str = "agent",
    ) -> MutationResult:
        modules = self._state(project, branch)
        if qualified_name in modules:
            raise ValidationError("DUPLICATE_MODULE", f"module {qualified_name!r} already exists")
        modules[qualified_name] = {
            "kind": "module",
            "name": qualified_name,
            "imports": [],
            "functions": [],
        }
        created: list[str] = []
        modules[qualified_name] = ensure_node_ids(modules[qualified_name], created)
        revision = self._commit(
            project,
            branch,
            modules,
            message=f"add module {qualified_name}",
            author=author,
            operations=[("add_module", qualified_name, {"module": qualified_name})],
        )
        return MutationResult(revision, branch, tuple(created))

    def add_import(
        self,
        project: str,
        branch: str,
        module: str,
        imported_module: str,
        *,
        author: str = "agent",
    ) -> MutationResult:
        modules = self._state(project, branch)
        target = self._module(modules, module)
        if imported_module not in modules:
            raise ValidationError(
                "UNKNOWN_MODULE",
                f"cannot import unknown module {imported_module!r}",
            )
        imports = list(target.get("imports", []))
        if imported_module not in imports:
            imports.append(imported_module)
        target["imports"] = sorted(imports)
        revision = self._commit(
            project,
            branch,
            modules,
            message=f"import {imported_module} in {module}",
            author=author,
            operations=[("add_import", module, {"import": imported_module})],
        )
        return MutationResult(revision, branch, ())

    def create_function(
        self,
        project: str,
        branch: str,
        module: str,
        name: str,
        *,
        params: list[JsonObject],
        returns: str,
        author: str = "agent",
    ) -> MutationResult:
        """Create a syntactically valid draft function with one statement hole."""
        function: JsonObject = {
            "kind": "fn",
            "name": name,
            "params": params,
            "returns": returns,
            "body": [{"kind": "hole", "category": "statement"}],
        }
        validate_function_shape(function)
        modules = self._state(project, branch)
        target = self._module(modules, module)
        if self._find_function(target, name) is not None:
            raise ValidationError("DUPLICATE_FUNCTION", f"function {module}.{name} already exists")
        created: list[str] = []
        function = ensure_node_ids(function, created)
        target["functions"].append(function)
        revision = self._commit(
            project,
            branch,
            modules,
            message=f"declare {module}.{name}",
            author=author,
            operations=[("create_function", f"{module}.{name}", function)],
        )
        return MutationResult(revision, branch, tuple(created))

    def upsert_function(
        self,
        project: str,
        branch: str,
        module: str,
        function: JsonObject,
        *,
        finalize: bool = True,
        author: str = "agent",
    ) -> MutationResult:
        """Insert or replace a complete function subtree in one validated operation."""
        validate_function_shape(function)
        modules = self._state(project, branch)
        target = self._module(modules, module)
        created: list[str] = []
        function = ensure_node_ids(copy.deepcopy(function), created)
        existing = self._find_function(target, function["name"])
        if existing is None:
            target["functions"].append(function)
            operation = "add_function"
        else:
            index = target["functions"].index(existing)
            target["functions"][index] = function
            operation = "replace_function"
        if finalize:
            self._validate_state(modules)
        revision = self._commit(
            project,
            branch,
            modules,
            message=f"{operation.replace('_', ' ')} {module}.{function['name']}",
            author=author,
            operations=[(operation, f"{module}.{function['name']}", function)],
        )
        return MutationResult(revision, branch, tuple(created))

    def insert_statement(
        self,
        project: str,
        branch: str,
        module: str,
        function_name: str,
        statement: JsonObject,
        *,
        before_node_id: str | None = None,
        author: str = "agent",
    ) -> MutationResult:
        """Insert one fully valid statement subtree and reject malformed input immediately."""
        validate_statement_shape(statement)
        modules = self._state(project, branch)
        function = self._require_function(self._module(modules, module), function_name)
        created: list[str] = []
        statement = ensure_node_ids(copy.deepcopy(statement), created)
        if before_node_id is None:
            function["body"].append(statement)
        else:
            container, index = self._locate_list_item(function, before_node_id)
            container.insert(index, statement)
        validate_function_shape(function)
        revision = self._commit(
            project,
            branch,
            modules,
            message=f"insert statement in {module}.{function_name}",
            author=author,
            operations=[("insert_statement", before_node_id or function["id"], statement)],
        )
        return MutationResult(revision, branch, tuple(created))

    def replace_node(
        self,
        project: str,
        branch: str,
        module: str,
        node_id: str,
        replacement: JsonObject,
        *,
        author: str = "agent",
    ) -> MutationResult:
        """Replace one AST node by stable ID after grammar validation."""
        kind = replacement.get("kind")
        if kind in {"let", "set", "if", "while", "return", "expr", "hole"}:
            validate_statement_shape(replacement)
        else:
            raise ValidationError(
                "INVALID_REPLACEMENT",
                "prototype replace_node accepts statement nodes",
            )
        modules = self._state(project, branch)
        target = self._module(modules, module)
        container, index = self._locate_list_item(target, node_id)
        created: list[str] = []
        replacement = ensure_node_ids(copy.deepcopy(replacement), created)
        container[index] = replacement
        for function in target["functions"]:
            validate_function_shape(function)
        revision = self._commit(
            project,
            branch,
            modules,
            message=f"replace node {node_id}",
            author=author,
            operations=[("replace_node", node_id, replacement)],
        )
        return MutationResult(revision, branch, tuple(created))

    def finalize_function(
        self,
        project: str,
        branch: str,
        module: str,
        function_name: str,
        *,
        author: str = "agent",
    ) -> MutationResult:
        modules = self._state(project, branch)
        function = self._require_function(self._module(modules, module), function_name)
        interfaces = self._interfaces(modules)
        validate_function_semantics(function, interfaces)
        revision = self._commit(
            project,
            branch,
            modules,
            message=f"finalize {module}.{function_name}",
            author=author,
            operations=[("finalize_function", f"{module}.{function_name}", {})],
        )
        return MutationResult(revision, branch, ())

    def add_document(
        self,
        project: str,
        branch: str,
        *,
        scope_kind: str,
        scope_name: str,
        title: str,
        body: str,
        author: str = "agent",
    ) -> MutationResult:
        self.project_id(project)
        parent = self.branch_head(project, branch)
        modules = self._state_at_revision(parent)
        content_hash = self.db.hash_value(
            {"scope_kind": scope_kind, "scope_name": scope_name, "title": title, "body": body}
        )
        document_id = str(uuid4())
        with self.db.transaction() as conn:
            existing = conn.execute(
                "SELECT id FROM documents WHERE content_hash = ?", (content_hash,)
            ).fetchone()
            if existing is not None:
                document_id = str(existing["id"])
            else:
                conn.execute(
                    """INSERT INTO documents(id, scope_kind, scope_name, title, body, content_hash)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (document_id, scope_kind, scope_name, title, body, content_hash),
                )
        revision = self._commit(
            project,
            branch,
            modules,
            message=f"add design context: {title}",
            author=author,
            operations=[("add_document", scope_name, {"document_id": document_id})],
            extra_document_ids=[document_id],
        )
        return MutationResult(revision, branch, ())

    def context_for_symbol(
        self, project: str, branch: str, qualified_name: str
    ) -> list[JsonObject]:
        revision = self.branch_head(project, branch)
        module_name, _, symbol_name = qualified_name.rpartition(".")
        rows = self.db.connection.execute(
            """SELECT d.id, d.scope_kind, d.scope_name, d.title, d.body, d.content_hash
               FROM revision_documents rd
               JOIN documents d ON d.id = rd.document_id
               WHERE rd.revision_id = ?
                 AND ((d.scope_kind = 'project' AND d.scope_name = ?)
                   OR (d.scope_kind = 'module' AND d.scope_name = ?)
                   OR (d.scope_kind = 'symbol' AND d.scope_name IN (?, ?)))
               ORDER BY d.scope_kind, d.title""",
            (revision, project, module_name, qualified_name, symbol_name),
        ).fetchall()
        return [dict(row) for row in rows]

    def find_symbols(
        self,
        project: str,
        branch: str = "main",
        *,
        name: str | None = None,
    ) -> list[SymbolSummary]:
        modules = self._state(project, branch)
        result: list[SymbolSummary] = []
        for module_name, module in sorted(modules.items()):
            for function in module["functions"]:
                if name is not None and function["name"] != name:
                    continue
                params = ", ".join(item["type"] for item in function["params"])
                result.append(
                    SymbolSummary(
                        qualified_name=f"{module_name}.{function['name']}",
                        kind="function",
                        signature=f"({params}) -> {function['returns']}",
                        module=module_name,
                        node_id=function["id"],
                    )
                )
        return result

    def inspect_function(
        self, project: str, branch: str, qualified_name: str
    ) -> JsonObject:
        module_name, separator, function_name = qualified_name.rpartition(".")
        if not separator:
            matches = self.find_symbols(project, branch, name=qualified_name)
            if len(matches) != 1:
                raise NotFoundError(f"function {qualified_name!r} is not uniquely resolvable")
            module_name = matches[0].module
            function_name = qualified_name
        modules = self._state(project, branch)
        function = self._require_function(self._module(modules, module_name), function_name)
        return copy.deepcopy(function)

    def render(self, project: str, branch: str, module: str) -> str:
        modules = self._state(project, branch)
        return render_module(self._module(modules, module))

    def validate(self, project: str, branch: str = "main") -> None:
        self._validate_state(self._state(project, branch))

    def merge(
        self,
        project: str,
        *,
        target_branch: str,
        source_branch: str,
        author: str = "merge-agent",
    ) -> MergeResult:
        target_head = self.branch_head(project, target_branch)
        source_head = self.branch_head(project, source_branch)
        base = self._common_ancestor(target_head, source_head)
        base_state = self._state_at_revision(base)
        ours = self._state_at_revision(target_head)
        theirs = self._state_at_revision(source_head)
        merged, changed = self._merge_states(base_state, ours, theirs)
        self._validate_state(merged)
        revision = self._commit(
            project,
            target_branch,
            merged,
            message=f"merge {source_branch} into {target_branch}",
            author=author,
            operations=[("merge", target_branch, {"source": source_branch, "base": base})],
            parent2=source_head,
        )
        return MergeResult(revision, target_branch, source_branch, tuple(sorted(changed)))

    def _state(self, project: str, branch: str) -> dict[str, JsonObject]:
        return self._state_at_revision(self.branch_head(project, branch))

    def _state_at_revision(self, revision_id: str) -> dict[str, JsonObject]:
        rows = self.db.connection.execute(
            "SELECT qualified_name, ast_json FROM module_snapshots WHERE revision_id = ?",
            (revision_id,),
        ).fetchall()
        return {str(row["qualified_name"]): json.loads(row["ast_json"]) for row in rows}

    def _commit(
        self,
        project: str,
        branch: str,
        modules: dict[str, JsonObject],
        *,
        message: str,
        author: str,
        operations: Iterable[tuple[str, str | None, JsonObject]],
        parent2: str | None = None,
        extra_document_ids: Iterable[str] = (),
    ) -> str:
        project_id = self.project_id(project)
        parent1 = self.branch_head(project, branch)
        revision_id = str(uuid4())
        root_hash = self.db.hash_value(modules)
        parent_documents = self.db.connection.execute(
            "SELECT document_id FROM revision_documents WHERE revision_id = ?", (parent1,)
        ).fetchall()
        document_ids = {str(row["document_id"]) for row in parent_documents}
        document_ids.update(extra_document_ids)
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO revisions(
                       id, project_id, parent1_id, parent2_id, message, author, root_hash
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (revision_id, project_id, parent1, parent2, message, author, root_hash),
            )
            for module_name, ast in sorted(modules.items()):
                canonical = self.db.canonical_json(ast)
                conn.execute(
                    """INSERT INTO module_snapshots(revision_id, qualified_name, ast_json, ast_hash)
                       VALUES (?, ?, ?, ?)""",
                    (revision_id, module_name, canonical, self.db.hash_value(ast)),
                )
            for sequence, (kind, target, payload) in enumerate(operations):
                conn.execute(
                    """INSERT INTO operations(
                           id, revision_id, sequence_number, operation_kind, target, payload_json
                       ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid4()),
                        revision_id,
                        sequence,
                        kind,
                        target,
                        self.db.canonical_json(payload),
                    ),
                )
            for document_id in sorted(document_ids):
                conn.execute(
                    "INSERT INTO revision_documents(revision_id, document_id) VALUES (?, ?)",
                    (revision_id, document_id),
                )
            conn.execute(
                "UPDATE branches SET head_revision_id = ? WHERE project_id = ? AND name = ?",
                (revision_id, project_id, branch),
            )
        return revision_id

    @staticmethod
    def _module(modules: dict[str, JsonObject], name: str) -> JsonObject:
        try:
            return modules[name]
        except KeyError as exc:
            raise NotFoundError(f"module {name!r} not found") from exc

    @staticmethod
    def _find_function(module: JsonObject, name: str) -> JsonObject | None:
        return next((item for item in module["functions"] if item["name"] == name), None)

    @classmethod
    def _require_function(cls, module: JsonObject, name: str) -> JsonObject:
        function = cls._find_function(module, name)
        if function is None:
            raise NotFoundError(f"function {name!r} not found")
        return function

    @staticmethod
    def _locate_list_item(root: Any, node_id: str) -> tuple[list[Any], int]:
        if isinstance(root, list):
            for index, value in enumerate(root):
                if isinstance(value, dict) and value.get("id") == node_id:
                    return root, index
                try:
                    return Workspace._locate_list_item(value, node_id)
                except NotFoundError:
                    pass
        elif isinstance(root, dict):
            for value in root.values():
                try:
                    return Workspace._locate_list_item(value, node_id)
                except NotFoundError:
                    pass
        raise NotFoundError(f"node {node_id!r} not found in a replaceable list")

    @staticmethod
    def _interfaces(modules: dict[str, JsonObject]) -> dict[str, JsonObject]:
        interfaces: dict[str, JsonObject] = {}
        for module_name, module in modules.items():
            for function in module["functions"]:
                interfaces[f"{module_name}.{function['name']}"] = {
                    "params": copy.deepcopy(function["params"]),
                    "returns": function["returns"],
                }
        return interfaces

    @classmethod
    def _validate_state(cls, modules: dict[str, JsonObject]) -> None:
        interfaces = cls._interfaces(modules)
        for module in modules.values():
            for function in module["functions"]:
                validate_function_semantics(function, interfaces)

    def _parents(self, revision: str) -> tuple[str | None, str | None]:
        row = self.db.connection.execute(
            "SELECT parent1_id, parent2_id FROM revisions WHERE id = ?", (revision,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"revision {revision!r} not found")
        return row["parent1_id"], row["parent2_id"]

    def _ancestor_distances(self, revision: str) -> dict[str, int]:
        distances = {revision: 0}
        queue: deque[str] = deque([revision])
        while queue:
            current = queue.popleft()
            for parent in self._parents(current):
                if parent is not None and parent not in distances:
                    distances[parent] = distances[current] + 1
                    queue.append(parent)
        return distances

    def _common_ancestor(self, left: str, right: str) -> str:
        left_distances = self._ancestor_distances(left)
        right_distances = self._ancestor_distances(right)
        common = set(left_distances) & set(right_distances)
        if not common:
            raise ConflictError(["branches have no common ancestor"])
        return min(common, key=lambda item: left_distances[item] + right_distances[item])

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
        for module_name in sorted(set(base) | set(ours) | set(theirs)):
            base_module = base.get(module_name)
            our_module = ours.get(module_name)
            their_module = theirs.get(module_name)
            if our_module == base_module:
                if their_module is not None:
                    merged[module_name] = copy.deepcopy(their_module)
                    changed.add(module_name)
                continue
            if their_module == base_module:
                if our_module is not None:
                    merged[module_name] = copy.deepcopy(our_module)
                continue
            if our_module == their_module:
                if our_module is not None:
                    merged[module_name] = copy.deepcopy(our_module)
                continue
            if base_module is None and our_module is not None and their_module is not None:
                pass
            elif our_module is None or their_module is None:
                conflicts.append(f"module:{module_name}")
                continue
            merged_module, module_conflicts, module_changed = cls._merge_module(
                module_name, base_module, our_module, their_module
            )
            merged[module_name] = merged_module
            conflicts.extend(module_conflicts)
            changed.update(module_changed)
        if conflicts:
            raise ConflictError(conflicts)
        return merged, changed

    @staticmethod
    def _merge_module(
        module_name: str,
        base: JsonObject | None,
        ours: JsonObject,
        theirs: JsonObject,
    ) -> tuple[JsonObject, list[str], set[str]]:
        base = base or {"kind": "module", "name": module_name, "imports": [], "functions": []}
        result = copy.deepcopy(ours)
        result["imports"] = sorted(set(ours.get("imports", [])) | set(theirs.get("imports", [])))
        base_functions = {item["name"]: item for item in base["functions"]}
        our_functions = {item["name"]: item for item in ours["functions"]}
        their_functions = {item["name"]: item for item in theirs["functions"]}
        functions: list[JsonObject] = []
        conflicts: list[str] = []
        changed: set[str] = set()
        for name in sorted(set(base_functions) | set(our_functions) | set(their_functions)):
            base_value = base_functions.get(name)
            our_value = our_functions.get(name)
            their_value = their_functions.get(name)
            if our_value == base_value:
                chosen = their_value
                if chosen != base_value:
                    changed.add(f"{module_name}.{name}")
            elif their_value == base_value or our_value == their_value:
                chosen = our_value
            else:
                conflicts.append(f"symbol:{module_name}.{name}")
                continue
            if chosen is not None:
                functions.append(copy.deepcopy(chosen))
        result["functions"] = functions
        return result, conflicts, changed
