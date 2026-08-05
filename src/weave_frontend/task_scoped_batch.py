"""Task-bound structural batches with enforced document scope and audit identity."""

from __future__ import annotations

from typing import Any

from .batch_edit import (
    MAX_BATCH_OPERATIONS,
    BatchOperationError,
    EditBatchExecutor,
)
from .errors import NotFoundError, ValidationError
from .sexpr import JsonObject, validate_tree, walk_nodes
from .task_contracts import TASK_CONTRACT_FORMAT, TaskContractRegistry

TASK_AUDIT_FORMAT = "weave-task-audit-v1"


class TaskScopedBatchExecutor:
    """Apply one ordinary structural batch under one exact task contract."""

    def __init__(
        self,
        registry: TaskContractRegistry,
        batches: EditBatchExecutor,
    ) -> None:
        self.registry = registry
        self.batches = batches
        self.workspace = registry.workspace

    def apply(
        self,
        project: str,
        task: str,
        document: str,
        operations: list[dict[str, Any]],
        *,
        branch: str = "main",
        actor: str,
        expected_revision_id: str | None = None,
        message: str | None = None,
        include_operation_results: bool = False,
    ) -> dict[str, Any]:
        """Validate one task contract and publish one task-attributed batch."""

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
        if not isinstance(actor, str) or not actor:
            raise ValidationError(
                "INVALID_TASK_ACTOR",
                "actor must be a non-empty string",
            )

        base_revision_id = self.workspace.branch_head(project, branch)
        if expected_revision_id is not None and expected_revision_id != base_revision_id:
            raise ValidationError(
                "STALE_REVISION",
                "branch head does not match expected_revision_id",
            )
        state = self.workspace._state_at_revision(base_revision_id)
        task_name = self.registry._name(task)
        task_document = self.registry.storage_document(task_name)
        task_root = state.get(task_document)
        if task_root is None:
            raise NotFoundError(f"task contract {task_name!r} not found")
        contract = self.registry._parse_tree(task_root, name=task_name)
        self.registry._validate_references(state, contract)
        self.registry.require_executable(
            state,
            contract,
            branch=branch,
            actor=actor,
            document=document,
        )
        contract_hash = self.registry.contract_hash(contract)
        task_revision_id = self.registry._latest_task_revision(
            base_revision_id,
            task_document,
        )
        audit_context = {
            "format": TASK_AUDIT_FORMAT,
            "contract_format": TASK_CONTRACT_FORMAT,
            "task": task_name,
            "contract_hash": contract_hash,
            "task_revision_id": task_revision_id,
            "task_base_revision_id": contract["base_revision_id"],
            "owner": contract["owner"],
            "actor": actor,
        }

        root = self.workspace._document(state, document)
        aliases: dict[str, str] = {}
        operation_log: list[tuple[str, str | None, JsonObject]] = []
        operation_results: list[dict[str, Any]] = []
        created_count = 0
        deleted_count = 0
        for index, raw in enumerate(operations):
            operation_name = raw.get("op") if isinstance(raw, dict) else None
            try:
                result, log_entry, created, deleted = self.batches._apply_one(
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
            kind, target, payload = log_entry
            operation_log.append(
                (
                    kind,
                    target,
                    {**payload, "task_contract": audit_context},
                )
            )
            operation_results.append(result)
            created_count += created
            deleted_count += deleted

        validate_tree(root)
        self.workspace._validate_state(state)
        revision_id = self.batches._commit_if_head(
            project,
            branch,
            state,
            base_revision_id=base_revision_id,
            message=message or f"apply task {task_name} structural edits",
            author=actor,
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
            "task": task_name,
            "task_revision_id": task_revision_id,
            "task_base_revision_id": contract["base_revision_id"],
            "task_contract_hash": contract_hash,
            "task_owner": contract["owner"],
            "task_actor": actor,
            "task_scope_enforced": True,
        }
        if include_operation_results:
            response["operation_results"] = operation_results
        return response
