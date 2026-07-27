"""Revisioned document-scoped work contracts for autonomous coding agents."""

from __future__ import annotations

import re
from typing import Any

from .errors import NotFoundError, ValidationError
from .project_metadata import TASK_CONTRACT_PREFIX, is_project_metadata_document
from .sexpr import JsonObject, head_symbol, make_atom, make_form, validate_tree

TASK_CONTRACT_FORMAT = "weave-task-contract-v1"
TASK_CONTRACT_HEAD = "task-contract"
TASK_CONTRACT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
TASK_CONTRACT_STATUSES = {
    "open",
    "in_progress",
    "blocked",
    "ready_for_review",
    "complete",
}
TASK_ACTIVE_STATUSES = {"open", "in_progress"}
MAX_TASK_TEXT_CHARS = 16_000
MAX_TASK_ITEMS = 64
MAX_TASK_ITEM_CHARS = 2_000
MAX_TASK_LIST_PAGE = 100

_STATUS_TRANSITIONS = {
    "open": {"in_progress", "blocked", "complete"},
    "in_progress": {"blocked", "ready_for_review", "complete"},
    "blocked": {"in_progress"},
    "ready_for_review": {"in_progress", "complete"},
    "complete": set(),
}
_SINGLE_FIELDS = (
    ("format", "format"),
    ("name", "name"),
    ("branch", "branch"),
    ("base_revision_id", "base-revision"),
    ("owner", "owner"),
    ("objective", "objective"),
    ("status", "status"),
)
_LIST_FIELDS = (
    ("allowed_documents", "allowed-documents"),
    ("dependencies", "dependencies"),
    ("required_tests", "required-tests"),
    ("acceptance_criteria", "acceptance-criteria"),
)


class TaskContractRegistry:
    """Create, inspect, and transition immutable branch-bound task contracts."""

    def __init__(self, workspace: Any) -> None:
        self.workspace = workspace

    def create(
        self,
        project: str,
        branch: str,
        name: str,
        *,
        owner: str,
        objective: str,
        allowed_documents: list[str],
        dependencies: list[str] | None = None,
        required_tests: list[str] | None = None,
        acceptance_criteria: list[str] | None = None,
        status: str = "open",
        expected_revision_id: str | None = None,
        author: str | None = None,
    ) -> dict[str, Any]:
        """Publish one task contract against the exact current branch head."""

        task_name = self._name(name)
        base_revision_id, state = self.workspace._state_for_write(
            project,
            branch,
            expected_revision_id=expected_revision_id,
        )
        storage_document = self.storage_document(task_name)
        if storage_document in state:
            raise ValidationError(
                "DUPLICATE_TASK_CONTRACT",
                f"task contract {task_name!r} already exists",
            )
        config = self._normalize(
            name=task_name,
            branch=branch,
            base_revision_id=base_revision_id,
            owner=owner,
            objective=objective,
            status=status,
            allowed_documents=allowed_documents,
            dependencies=dependencies,
            required_tests=required_tests,
            acceptance_criteria=acceptance_criteria,
        )
        self._validate_references(state, config, creating=True)
        root = self._build_tree(config)
        validate_tree(root)
        state[storage_document] = root
        validate_task_contract_references(state)
        contract_hash = self.contract_hash(config)
        revision_id = self.workspace._commit(
            project,
            branch,
            state,
            message=f"create task contract {task_name}",
            author=author or owner,
            operations=[
                (
                    "create_task_contract",
                    storage_document,
                    {
                        "format": TASK_CONTRACT_FORMAT,
                        "task": task_name,
                        "contract_hash": contract_hash,
                        "owner": config["owner"],
                        "base_revision_id": base_revision_id,
                    },
                )
            ],
            expected_branch_heads={branch: base_revision_id},
            stale_error_code="STALE_BRANCH_HEAD",
        )
        return self._result(
            config,
            branch=branch,
            selected_revision_id=revision_id,
            branch_head_revision_id=revision_id,
            root=root,
            contract_hash=contract_hash,
            task_revision_id=revision_id,
        )

    def get(
        self,
        project: str,
        name: str,
        *,
        branch: str = "main",
        revision_id: str | None = None,
    ) -> dict[str, Any]:
        """Read one contract from a branch head or exact immutable revision."""

        task_name = self._name(name)
        branch_head_revision_id = self.workspace.branch_head(project, branch)
        selected_revision_id = revision_id or branch_head_revision_id
        self._require_project_revision(project, selected_revision_id)
        state = self.workspace._state_at_revision(selected_revision_id)
        storage_document = self.storage_document(task_name)
        root = state.get(storage_document)
        if root is None:
            raise NotFoundError(f"task contract {task_name!r} not found")
        config = self._parse_tree(root, name=task_name)
        self._validate_references(state, config, creating=False)
        return self._result(
            config,
            branch=branch,
            selected_revision_id=selected_revision_id,
            branch_head_revision_id=branch_head_revision_id,
            root=root,
            contract_hash=self.contract_hash(config),
            task_revision_id=self._latest_task_revision(
                project,
                selected_revision_id,
                storage_document,
            ),
        )

    def list_page(
        self,
        project: str,
        *,
        branch: str = "main",
        revision_id: str | None = None,
        start_after_name: str | None = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        """Return one stable lexical page of task summaries."""

        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_TASK_LIST_PAGE:
            raise ValidationError(
                "INVALID_TASK_LIST_LIMIT",
                f"limit must be an integer between 1 and {MAX_TASK_LIST_PAGE}",
            )
        if start_after_name is not None:
            self._name(start_after_name)
        branch_head_revision_id = self.workspace.branch_head(project, branch)
        selected_revision_id = revision_id or branch_head_revision_id
        self._require_project_revision(project, selected_revision_id)
        state = self.workspace._state_at_revision(selected_revision_id)
        names = sorted(
            document[len(TASK_CONTRACT_PREFIX) :]
            for document in state
            if document.startswith(TASK_CONTRACT_PREFIX)
        )
        if start_after_name is None:
            start = 0
        else:
            try:
                start = names.index(start_after_name) + 1
            except ValueError as exc:
                raise ValidationError(
                    "INVALID_TASK_LIST_CURSOR",
                    "start_after_name must identify a task in the selected revision",
                ) from exc
        selected = names[start : start + limit]
        tasks = []
        for task_name in selected:
            config = self._parse_tree(
                state[self.storage_document(task_name)],
                name=task_name,
            )
            self._validate_references(state, config, creating=False)
            tasks.append(
                {
                    "name": task_name,
                    "branch": config["branch"],
                    "owner": config["owner"],
                    "status": config["status"],
                    "base_revision_id": config["base_revision_id"],
                    "allowed_document_count": len(config["allowed_documents"]),
                    "dependency_count": len(config["dependencies"]),
                    "required_test_count": len(config["required_tests"]),
                    "acceptance_criterion_count": len(config["acceptance_criteria"]),
                    "contract_hash": self.contract_hash(config),
                }
            )
        has_more = start + len(selected) < len(names)
        payload = {
            "format": "weave-task-contract-page-v1",
            "project": project,
            "branch": branch,
            "revision_id": selected_revision_id,
            "branch_head_revision_id": branch_head_revision_id,
            "revision_is_branch_head": selected_revision_id == branch_head_revision_id,
            "start_after_name": start_after_name,
            "limit": limit,
            "total_task_count": len(names),
            "returned_task_count": len(tasks),
            "has_more": has_more,
            "next_after_name": selected[-1] if has_more and selected else None,
            "tasks": tasks,
        }
        return {**payload, "page_id": self.workspace.db.hash_value(payload)}

    def set_status(
        self,
        project: str,
        branch: str,
        name: str,
        status: str,
        *,
        actor: str,
        expected_revision_id: str | None = None,
    ) -> dict[str, Any]:
        """Publish one owner-authorized status transition."""

        task_name = self._name(name)
        base_revision_id, state = self.workspace._state_for_write(
            project,
            branch,
            expected_revision_id=expected_revision_id,
        )
        storage_document = self.storage_document(task_name)
        root = state.get(storage_document)
        if root is None:
            raise NotFoundError(f"task contract {task_name!r} not found")
        config = self._parse_tree(root, name=task_name)
        if config["branch"] != branch:
            raise ValidationError(
                "TASK_BRANCH_MISMATCH",
                f"task {task_name!r} is bound to branch {config['branch']!r}",
            )
        if actor != config["owner"]:
            raise ValidationError(
                "TASK_OWNER_MISMATCH",
                f"task {task_name!r} is owned by {config['owner']!r}",
            )
        normalized_status = self._status(status)
        current_status = str(config["status"])
        if normalized_status == current_status:
            raise ValidationError(
                "TASK_STATUS_UNCHANGED",
                f"task {task_name!r} already has status {current_status!r}",
            )
        if normalized_status not in _STATUS_TRANSITIONS[current_status]:
            raise ValidationError(
                "INVALID_TASK_STATUS_TRANSITION",
                f"task status cannot move from {current_status!r} to {normalized_status!r}",
            )
        config = {**config, "status": normalized_status}
        updated_root = self._build_tree(config, existing=root)
        state[storage_document] = updated_root
        validate_task_contract_references(state)
        contract_hash = self.contract_hash(config)
        revision_id = self.workspace._commit(
            project,
            branch,
            state,
            message=f"set task {task_name} status {normalized_status}",
            author=actor,
            operations=[
                (
                    "set_task_status",
                    storage_document,
                    {
                        "format": TASK_CONTRACT_FORMAT,
                        "task": task_name,
                        "from_status": current_status,
                        "to_status": normalized_status,
                        "contract_hash": contract_hash,
                    },
                )
            ],
            expected_branch_heads={branch: base_revision_id},
            stale_error_code="STALE_BRANCH_HEAD",
        )
        return self._result(
            config,
            branch=branch,
            selected_revision_id=revision_id,
            branch_head_revision_id=revision_id,
            root=updated_root,
            contract_hash=contract_hash,
            task_revision_id=revision_id,
        )

    @staticmethod
    def storage_document(name: str) -> str:
        return f"{TASK_CONTRACT_PREFIX}{name}"

    @classmethod
    def contract_hash(cls, config: dict[str, Any]) -> str:
        return cls._hashable(config)

    @staticmethod
    def _hashable(config: dict[str, Any]) -> str:
        # Registry instances use the workspace hash function at call sites; this fallback
        # keeps parsed contracts independently content-addressable in validation code.
        import hashlib
        import json

        return hashlib.sha256(
            json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def require_executable(
        self,
        state: dict[str, JsonObject],
        config: dict[str, Any],
        *,
        branch: str,
        actor: str,
        document: str,
    ) -> None:
        """Reject task-bound execution that violates owner, state, or dependencies."""

        if config["branch"] != branch:
            raise ValidationError(
                "TASK_BRANCH_MISMATCH",
                f"task {config['name']!r} is bound to branch {config['branch']!r}",
            )
        if actor != config["owner"]:
            raise ValidationError(
                "TASK_OWNER_MISMATCH",
                f"task {config['name']!r} is owned by {config['owner']!r}",
            )
        if config["status"] not in TASK_ACTIVE_STATUSES:
            raise ValidationError(
                "TASK_NOT_ACTIVE",
                f"task {config['name']!r} has non-executable status {config['status']!r}",
            )
        if document not in config["allowed_documents"]:
            raise ValidationError(
                "TASK_SCOPE_VIOLATION",
                f"document {document!r} is outside task {config['name']!r} scope",
            )
        incomplete = []
        for dependency in config["dependencies"]:
            dependency_root = state.get(self.storage_document(dependency))
            if dependency_root is None:
                incomplete.append(dependency)
                continue
            dependency_config = self._parse_tree(dependency_root, name=dependency)
            if dependency_config["status"] != "complete":
                incomplete.append(dependency)
        if incomplete:
            raise ValidationError(
                "TASK_DEPENDENCIES_INCOMPLETE",
                f"task dependencies are not complete: {sorted(incomplete)!r}",
            )

    def _validate_references(
        self,
        state: dict[str, JsonObject],
        config: dict[str, Any],
        *,
        creating: bool,
    ) -> None:
        for document in config["allowed_documents"]:
            if is_project_metadata_document(document) or document not in state:
                raise ValidationError(
                    "INVALID_TASK_DOCUMENT_REFERENCE",
                    f"task document {document!r} must be an existing compiler source",
                )
        for test_name in config["required_tests"]:
            if f"@test-target/{test_name}" not in state:
                raise ValidationError(
                    "INVALID_TASK_TEST_REFERENCE",
                    f"required test {test_name!r} does not exist",
                )
        for dependency in config["dependencies"]:
            if dependency == config["name"]:
                raise ValidationError(
                    "INVALID_TASK_DEPENDENCY",
                    "a task cannot depend on itself",
                )
            if self.storage_document(dependency) not in state:
                raise ValidationError(
                    "INVALID_TASK_DEPENDENCY",
                    f"task dependency {dependency!r} does not exist",
                )
        if not creating and config["branch"] == "":
            raise ValidationError("INVALID_TASK_CONTRACT", "task branch must not be empty")

    @classmethod
    def _normalize(
        cls,
        *,
        name: Any,
        branch: Any,
        base_revision_id: Any,
        owner: Any,
        objective: Any,
        status: Any,
        allowed_documents: Any,
        dependencies: Any,
        required_tests: Any,
        acceptance_criteria: Any,
        expected_format: Any = TASK_CONTRACT_FORMAT,
    ) -> dict[str, Any]:
        if expected_format != TASK_CONTRACT_FORMAT:
            raise ValidationError(
                "INVALID_TASK_CONTRACT",
                f"task contract format must be {TASK_CONTRACT_FORMAT!r}",
            )
        return {
            "format": TASK_CONTRACT_FORMAT,
            "name": cls._name(name),
            "branch": cls._text("branch", branch, maximum=256),
            "base_revision_id": cls._text(
                "base_revision_id", base_revision_id, maximum=256
            ),
            "owner": cls._text("owner", owner, maximum=256),
            "objective": cls._text(
                "objective", objective, maximum=MAX_TASK_TEXT_CHARS
            ),
            "status": cls._status(status),
            "allowed_documents": cls._items(
                "allowed_documents", allowed_documents, pattern=None
            ),
            "dependencies": cls._items(
                "dependencies", dependencies or [], pattern=TASK_CONTRACT_NAME
            ),
            "required_tests": cls._items(
                "required_tests", required_tests or [], pattern=TASK_CONTRACT_NAME
            ),
            "acceptance_criteria": cls._items(
                "acceptance_criteria", acceptance_criteria or [], pattern=None
            ),
        }

    @classmethod
    def _parse_tree(cls, root: JsonObject, *, name: str) -> dict[str, Any]:
        if head_symbol(root) != TASK_CONTRACT_HEAD:
            raise ValidationError(
                "INVALID_TASK_CONTRACT",
                f"task {name!r} metadata must use {TASK_CONTRACT_HEAD!r}",
            )
        fields: dict[str, JsonObject] = {}
        for child in root.get("children", [])[1:]:
            field_head = head_symbol(child)
            if field_head is None or field_head in fields:
                raise ValidationError(
                    "INVALID_TASK_CONTRACT",
                    f"task {name!r} contains invalid or duplicate fields",
                )
            fields[field_head] = child
        raw: dict[str, Any] = {}
        expected_heads = {head for _, head in (*_SINGLE_FIELDS, *_LIST_FIELDS)}
        unknown = sorted(set(fields) - expected_heads)
        if unknown:
            raise ValidationError(
                "INVALID_TASK_CONTRACT",
                f"task {name!r} contains unknown fields {unknown!r}",
            )
        for key, head in _SINGLE_FIELDS:
            raw[key] = cls._single_value(fields.get(head), head)
        for key, head in _LIST_FIELDS:
            raw[key] = cls._list_values(fields.get(head), head)
        config = cls._normalize(
            name=raw["name"],
            branch=raw["branch"],
            base_revision_id=raw["base_revision_id"],
            owner=raw["owner"],
            objective=raw["objective"],
            status=raw["status"],
            allowed_documents=raw["allowed_documents"],
            dependencies=raw["dependencies"],
            required_tests=raw["required_tests"],
            acceptance_criteria=raw["acceptance_criteria"],
            expected_format=raw["format"],
        )
        if config["name"] != name:
            raise ValidationError(
                "INVALID_TASK_CONTRACT",
                f"task metadata name {config['name']!r} does not match {name!r}",
            )
        return config

    @classmethod
    def _build_tree(
        cls,
        config: dict[str, Any],
        *,
        existing: JsonObject | None = None,
    ) -> JsonObject:
        old_fields = cls._field_map(existing)
        root = make_form(
            TASK_CONTRACT_HEAD,
            node_id=existing.get("id") if existing is not None else None,
        )
        for key, head in _SINGLE_FIELDS:
            old = old_fields.get(head)
            field = make_form(head, node_id=old.get("id") if old else None)
            old_atom = old.get("children", [None, None])[1] if old else None
            field["children"].append(
                make_atom(
                    "string",
                    config[key],
                    node_id=(old_atom.get("id") if isinstance(old_atom, dict) else None),
                )
            )
            root["children"].append(field)
        for key, head in _LIST_FIELDS:
            old = old_fields.get(head)
            field = make_form(head, node_id=old.get("id") if old else None)
            old_atoms = old.get("children", [])[1:] if old else []
            for index, value in enumerate(config[key]):
                node_id = (
                    old_atoms[index].get("id")
                    if index < len(old_atoms) and isinstance(old_atoms[index], dict)
                    else None
                )
                field["children"].append(make_atom("string", value, node_id=node_id))
            root["children"].append(field)
        return root

    @staticmethod
    def _field_map(root: JsonObject | None) -> dict[str, JsonObject]:
        if root is None:
            return {}
        return {
            str(head_symbol(child)): child
            for child in root.get("children", [])[1:]
            if head_symbol(child) is not None
        }

    @staticmethod
    def _single_value(field: JsonObject | None, name: str) -> Any:
        if field is None or len(field.get("children", [])) != 2:
            raise ValidationError(
                "INVALID_TASK_CONTRACT",
                f"task field {name!r} requires exactly one value",
            )
        atom = field["children"][1]
        if atom.get("kind") != "string":
            raise ValidationError(
                "INVALID_TASK_CONTRACT",
                f"task field {name!r} requires one string",
            )
        return atom.get("value")

    @staticmethod
    def _list_values(field: JsonObject | None, name: str) -> list[Any]:
        if field is None:
            raise ValidationError(
                "INVALID_TASK_CONTRACT",
                f"task field {name!r} is required",
            )
        values = []
        for atom in field.get("children", [])[1:]:
            if atom.get("kind") != "string":
                raise ValidationError(
                    "INVALID_TASK_CONTRACT",
                    f"task field {name!r} accepts only strings",
                )
            values.append(atom.get("value"))
        return values

    @staticmethod
    def _name(value: Any) -> str:
        if not isinstance(value, str) or not TASK_CONTRACT_NAME.fullmatch(value):
            raise ValidationError(
                "INVALID_TASK_NAME",
                "task names must use letters, digits, '.', '_', or '-'",
            )
        return value

    @staticmethod
    def _status(value: Any) -> str:
        if not isinstance(value, str) or value not in TASK_CONTRACT_STATUSES:
            raise ValidationError(
                "INVALID_TASK_STATUS",
                f"status must be one of {sorted(TASK_CONTRACT_STATUSES)}",
            )
        return value

    @staticmethod
    def _text(name: str, value: Any, *, maximum: int) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(
                "INVALID_TASK_CONTRACT",
                f"{name} must be a non-empty string",
            )
        if len(value) > maximum:
            raise ValidationError(
                "INVALID_TASK_CONTRACT",
                f"{name} must contain at most {maximum} characters",
            )
        return value

    @classmethod
    def _items(
        cls,
        name: str,
        values: Any,
        *,
        pattern: re.Pattern[str] | None,
    ) -> list[str]:
        if not isinstance(values, list) or len(values) > MAX_TASK_ITEMS:
            raise ValidationError(
                "INVALID_TASK_CONTRACT",
                f"{name} must be a list with at most {MAX_TASK_ITEMS} items",
            )
        normalized = [
            cls._text(f"{name} item", value, maximum=MAX_TASK_ITEM_CHARS)
            for value in values
        ]
        if pattern is not None and any(not pattern.fullmatch(value) for value in normalized):
            raise ValidationError(
                "INVALID_TASK_CONTRACT",
                f"{name} contains an invalid task or test name",
            )
        if len(normalized) != len(set(normalized)):
            raise ValidationError(
                "INVALID_TASK_CONTRACT",
                f"{name} must not contain duplicates",
            )
        if name == "allowed_documents" and not normalized:
            raise ValidationError(
                "INVALID_TASK_CONTRACT",
                "allowed_documents must contain at least one compiler source",
            )
        return normalized

    def _latest_task_revision(
        self,
        project: str,
        selected_revision_id: str,
        storage_document: str,
    ) -> str:
        current: str | None = selected_revision_id
        while current is not None:
            row = self.workspace.db.connection.execute(
                """SELECT 1 FROM operations
                   WHERE revision_id = ? AND target = ?
                     AND operation_kind IN ('create_task_contract', 'set_task_status')
                   LIMIT 1""",
                (current, storage_document),
            ).fetchone()
            if row is not None:
                return current
            parent = self.workspace.db.connection.execute(
                "SELECT parent1_id FROM revisions WHERE id = ?",
                (current,),
            ).fetchone()
            current = str(parent["parent1_id"]) if parent and parent["parent1_id"] else None
        raise ValidationError(
            "INVALID_TASK_CONTRACT",
            f"task {storage_document!r} has no audit operation in first-parent history",
        )

    def _require_project_revision(self, project: str, revision_id: str) -> None:
        row = self.workspace.db.connection.execute(
            """SELECT 1 FROM revisions r
               JOIN projects p ON p.id = r.project_id
               WHERE r.id = ? AND p.name = ?""",
            (revision_id, project),
        ).fetchone()
        if row is None:
            raise NotFoundError(
                f"revision {revision_id!r} does not belong to project {project!r}"
            )

    @staticmethod
    def _result(
        config: dict[str, Any],
        *,
        branch: str,
        selected_revision_id: str,
        branch_head_revision_id: str,
        root: JsonObject,
        contract_hash: str,
        task_revision_id: str,
    ) -> dict[str, Any]:
        return {
            **config,
            "selected_branch": branch,
            "revision_id": selected_revision_id,
            "branch_head_revision_id": branch_head_revision_id,
            "revision_is_branch_head": selected_revision_id == branch_head_revision_id,
            "task_revision_id": task_revision_id,
            "storage_document": TaskContractRegistry.storage_document(config["name"]),
            "root_node_id": root["id"],
            "contract_hash": contract_hash,
        }


def task_contracts(state: dict[str, JsonObject]) -> dict[str, dict[str, Any]]:
    """Parse every task contract from one exact project state."""

    result = {}
    for document, root in sorted(state.items()):
        if not document.startswith(TASK_CONTRACT_PREFIX):
            continue
        name = document[len(TASK_CONTRACT_PREFIX) :]
        result[name] = TaskContractRegistry._parse_tree(root, name=name)
    return result


def validate_task_contract_references(state: dict[str, JsonObject]) -> None:
    """Reject dangling source/test/dependency references and dependency cycles."""

    contracts = task_contracts(state)
    registry = TaskContractRegistry.__new__(TaskContractRegistry)
    registry.workspace = None
    for config in contracts.values():
        TaskContractRegistry._validate_references(registry, state, config, creating=False)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str, path: list[str]) -> None:
        if name in visited:
            return
        if name in visiting:
            cycle = path[path.index(name) :] + [name]
            raise ValidationError(
                "TASK_DEPENDENCY_CYCLE",
                f"task dependency cycle detected: {' -> '.join(cycle)}",
            )
        visiting.add(name)
        for dependency in contracts[name]["dependencies"]:
            visit(dependency, [*path, dependency])
        visiting.remove(name)
        visited.add(name)

    for name in sorted(contracts):
        visit(name, [name])
