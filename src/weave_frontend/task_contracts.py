"""Revisioned persistence and lifecycle for branch-bound task contracts."""

from __future__ import annotations

from typing import Any

from .errors import NotFoundError, ValidationError
from .sexpr import JsonObject
from .task_contract_model import (
    MAX_TASK_LIST_PAGE,
    STATUS_TRANSITIONS,
    TASK_ACTIVE_STATUSES,
    TASK_CONTRACT_FORMAT,
    build_task_contract_tree,
    normalize_task_contract,
    parse_task_contract_tree,
    task_contract_hash,
    task_storage_document,
    validate_task_contract_config_references,
    validate_task_contract_references,
    validate_task_name,
    validate_task_status,
)


class TaskContractRegistry:
    """Create, inspect, and transition immutable task contracts."""

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
        task_name = validate_task_name(name)
        base_revision_id, state = self.workspace._state_for_write(
            project,
            branch,
            expected_revision_id=expected_revision_id,
        )
        storage_document = task_storage_document(task_name)
        if storage_document in state:
            raise ValidationError(
                "DUPLICATE_TASK_CONTRACT",
                f"task contract {task_name!r} already exists",
            )
        config = normalize_task_contract(
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
        validate_task_contract_config_references(state, config)
        root = build_task_contract_tree(config)
        state[storage_document] = root
        validate_task_contract_references(state)
        contract_hash = task_contract_hash(config)
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
        task_name = validate_task_name(name)
        branch_head_revision_id = self.workspace.branch_head(project, branch)
        selected_revision_id = revision_id or branch_head_revision_id
        self._require_project_revision(project, selected_revision_id)
        state = self.workspace._state_at_revision(selected_revision_id)
        storage_document = task_storage_document(task_name)
        root = state.get(storage_document)
        if root is None:
            raise NotFoundError(f"task contract {task_name!r} not found")
        config = parse_task_contract_tree(root, name=task_name)
        validate_task_contract_config_references(state, config)
        return self._result(
            config,
            branch=branch,
            selected_revision_id=selected_revision_id,
            branch_head_revision_id=branch_head_revision_id,
            root=root,
            task_revision_id=self._latest_task_revision(
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
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= MAX_TASK_LIST_PAGE
        ):
            raise ValidationError(
                "INVALID_TASK_LIST_LIMIT",
                f"limit must be an integer between 1 and {MAX_TASK_LIST_PAGE}",
            )
        if start_after_name is not None:
            validate_task_name(start_after_name)
        branch_head_revision_id = self.workspace.branch_head(project, branch)
        selected_revision_id = revision_id or branch_head_revision_id
        self._require_project_revision(project, selected_revision_id)
        state = self.workspace._state_at_revision(selected_revision_id)
        prefix = "@task/"
        names = sorted(document[len(prefix) :] for document in state if document.startswith(prefix))
        start = self._page_start(names, start_after_name)
        selected = names[start : start + limit]
        tasks = []
        for task_name in selected:
            config = parse_task_contract_tree(
                state[task_storage_document(task_name)],
                name=task_name,
            )
            validate_task_contract_config_references(state, config)
            tasks.append(self._summary(config))
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
        task_name = validate_task_name(name)
        base_revision_id, state = self.workspace._state_for_write(
            project,
            branch,
            expected_revision_id=expected_revision_id,
        )
        storage_document = task_storage_document(task_name)
        root = state.get(storage_document)
        if root is None:
            raise NotFoundError(f"task contract {task_name!r} not found")
        config = parse_task_contract_tree(root, name=task_name)
        self._require_owner_and_branch(config, branch=branch, actor=actor)
        normalized_status = validate_task_status(status)
        current_status = str(config["status"])
        if normalized_status == current_status:
            raise ValidationError(
                "TASK_STATUS_UNCHANGED",
                f"task {task_name!r} already has status {current_status!r}",
            )
        if normalized_status not in STATUS_TRANSITIONS[current_status]:
            raise ValidationError(
                "INVALID_TASK_STATUS_TRANSITION",
                f"task status cannot move from {current_status!r} to {normalized_status!r}",
            )
        config = {**config, "status": normalized_status}
        updated_root = build_task_contract_tree(config, existing=root)
        state[storage_document] = updated_root
        validate_task_contract_references(state)
        contract_hash = task_contract_hash(config)
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
            task_revision_id=revision_id,
        )

    def require_executable(
        self,
        state: dict[str, JsonObject],
        config: dict[str, Any],
        *,
        branch: str,
        actor: str,
        document: str,
    ) -> None:
        self._require_owner_and_branch(config, branch=branch, actor=actor)
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
            dependency_root = state.get(task_storage_document(dependency))
            if dependency_root is None:
                incomplete.append(dependency)
                continue
            dependency_config = parse_task_contract_tree(
                dependency_root,
                name=dependency,
            )
            if dependency_config["status"] != "complete":
                incomplete.append(dependency)
        if incomplete:
            raise ValidationError(
                "TASK_DEPENDENCIES_INCOMPLETE",
                f"task dependencies are not complete: {sorted(incomplete)!r}",
            )

    @staticmethod
    def storage_document(name: str) -> str:
        return task_storage_document(name)

    @staticmethod
    def contract_hash(config: dict[str, Any]) -> str:
        return task_contract_hash(config)

    @staticmethod
    def _parse_tree(root: JsonObject, *, name: str) -> dict[str, Any]:
        return parse_task_contract_tree(root, name=name)

    @staticmethod
    def _validate_references(
        state: dict[str, JsonObject],
        config: dict[str, Any],
        *,
        creating: bool = False,
    ) -> None:
        del creating
        validate_task_contract_config_references(state, config)

    @staticmethod
    def _name(value: Any) -> str:
        return validate_task_name(value)

    def _latest_task_revision(
        self,
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
            raise NotFoundError(f"revision {revision_id!r} does not belong to project {project!r}")

    @staticmethod
    def _require_owner_and_branch(
        config: dict[str, Any],
        *,
        branch: str,
        actor: str,
    ) -> None:
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

    @staticmethod
    def _page_start(names: list[str], start_after_name: str | None) -> int:
        if start_after_name is None:
            return 0
        try:
            return names.index(start_after_name) + 1
        except ValueError as exc:
            raise ValidationError(
                "INVALID_TASK_LIST_CURSOR",
                "start_after_name must identify a task in the selected revision",
            ) from exc

    @staticmethod
    def _summary(config: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": config["name"],
            "branch": config["branch"],
            "owner": config["owner"],
            "status": config["status"],
            "base_revision_id": config["base_revision_id"],
            "allowed_document_count": len(config["allowed_documents"]),
            "dependency_count": len(config["dependencies"]),
            "required_test_count": len(config["required_tests"]),
            "acceptance_criterion_count": len(config["acceptance_criteria"]),
            "contract_hash": task_contract_hash(config),
        }

    @staticmethod
    def _result(
        config: dict[str, Any],
        *,
        branch: str,
        selected_revision_id: str,
        branch_head_revision_id: str,
        root: JsonObject,
        task_revision_id: str,
    ) -> dict[str, Any]:
        return {
            **config,
            "selected_branch": branch,
            "revision_id": selected_revision_id,
            "branch_head_revision_id": branch_head_revision_id,
            "revision_is_branch_head": selected_revision_id == branch_head_revision_id,
            "task_revision_id": task_revision_id,
            "storage_document": task_storage_document(config["name"]),
            "root_node_id": root["id"],
            "contract_hash": task_contract_hash(config),
        }


__all__ = [
    "TASK_ACTIVE_STATUSES",
    "TASK_CONTRACT_FORMAT",
    "TaskContractRegistry",
    "validate_task_contract_references",
]
