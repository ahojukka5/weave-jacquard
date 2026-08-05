"""Resume snapshots extended with bounded revisioned task-contract orientation."""

from __future__ import annotations

from typing import Any

from .errors import NotFoundError
from .project_metadata import (
    BUILD_TARGET_PREFIX,
    TASK_CONTRACT_PREFIX,
    TEST_TARGET_PREFIX,
)
from .task_contracts import TaskContractRegistry
from .test_resume_snapshot import TestResumeSnapshotService

MAX_RESUME_TASKS = 100


class TaskResumeSnapshotService(TestResumeSnapshotService):
    """Compose exact program, test, checkpoint, and task orientation."""

    def __init__(
        self,
        workspace: Any,
        targets: Any,
        policies: Any,
        checkpoints: Any,
        tests: Any,
        tasks: TaskContractRegistry,
    ) -> None:
        super().__init__(workspace, targets, policies, checkpoints, tests)
        self.tasks = tasks

    def snapshot(
        self,
        project: str,
        branch: str = "main",
        *,
        task_limit: int = 50,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self._validate_limit("task_limit", task_limit, MAX_RESUME_TASKS)
        result = super().snapshot(project, branch, **kwargs)
        revision_id = str(result["revision_id"])
        entries, total = self._tasks(
            project,
            branch,
            revision_id,
            limit=task_limit,
        )
        result.pop("snapshot_id")
        result["limits"]["task_limit"] = task_limit
        result["task_count"] = total
        result["returned_task_count"] = len(entries)
        result["tasks_truncated"] = len(entries) < total
        result["tasks"] = entries
        result["task_recovery"] = {
            "tool": "task_list",
            "arguments": {
                "project": project,
                "branch": branch,
                "revision_id": revision_id,
            },
        }
        result["snapshot_id"] = self._snapshot_id(result)
        return result

    def _programs(
        self,
        modules: dict[str, dict[str, Any]],
        revision_id: str,
        *,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        excluded = self._metadata_prefixes()
        names = [
            name
            for name in self._program_document_names(modules)
            if not any(name.startswith(prefix) for prefix in excluded)
        ]
        page = names[:limit]
        return (
            [
                self._program_summary(
                    name,
                    modules[name],
                    revision_id=revision_id,
                )
                for name in page
            ],
            len(names),
        )

    def _require_program_documents(
        self,
        modules: dict[str, dict[str, Any]],
        documents: list[str],
    ) -> None:
        excluded = self._metadata_prefixes()
        for document in documents:
            if document not in modules or any(document.startswith(prefix) for prefix in excluded):
                raise NotFoundError(f"program document {document!r} not found")

    def _metadata_prefixes(self) -> tuple[str, ...]:
        return (BUILD_TARGET_PREFIX, TEST_TARGET_PREFIX, TASK_CONTRACT_PREFIX)

    def _tasks(
        self,
        project: str,
        branch: str,
        revision_id: str,
        *,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        modules = self._revision_modules(revision_id)
        names = sorted(name for name in modules if name.startswith(TASK_CONTRACT_PREFIX))
        page = names[:limit]
        result = []
        for storage_document in page:
            name = storage_document[len(TASK_CONTRACT_PREFIX) :]
            root = modules[storage_document]
            config = self.tasks._parse_tree(root, name=name)
            self.tasks._validate_references(modules, config, creating=False)
            result.append(
                {
                    "name": name,
                    "bound_branch": config["branch"],
                    "base_revision_id": config["base_revision_id"],
                    "owner": config["owner"],
                    "status": config["status"],
                    "objective": config["objective"][:512],
                    "objective_truncated": len(config["objective"]) > 512,
                    "allowed_documents": config["allowed_documents"],
                    "dependency_count": len(config["dependencies"]),
                    "required_test_count": len(config["required_tests"]),
                    "acceptance_criterion_count": len(config["acceptance_criteria"]),
                    "contract_hash": self.tasks.contract_hash(config),
                    "detail": {
                        "tool": "task_get",
                        "arguments": {
                            "project": project,
                            "name": name,
                            "branch": branch,
                            "revision_id": revision_id,
                        },
                    },
                }
            )
        return result, len(names)
