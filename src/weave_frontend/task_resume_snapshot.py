"""Resume snapshots extended with bounded revisioned task-contract orientation."""

from __future__ import annotations

import json
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
        revision_id: str,
        *,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        patterns = self._metadata_patterns()
        where = " AND ".join("qualified_name NOT LIKE ?" for _ in patterns)
        parameters = (revision_id, *patterns)
        total = int(
            self.workspace.db.connection.execute(
                f"""SELECT COUNT(*) AS count
                    FROM module_snapshots
                    WHERE revision_id = ? AND {where}""",
                parameters,
            ).fetchone()["count"]
        )
        rows = self.workspace.db.connection.execute(
            f"""SELECT qualified_name, ast_json
                FROM module_snapshots
                WHERE revision_id = ? AND {where}
                ORDER BY qualified_name
                LIMIT ?""",
            (*parameters, limit),
        ).fetchall()
        return (
            [
                self._program_summary(
                    str(row["qualified_name"]),
                    json.loads(str(row["ast_json"])),
                    revision_id=revision_id,
                )
                for row in rows
            ],
            total,
        )

    def _require_program_documents(
        self,
        revision_id: str,
        documents: list[str],
    ) -> None:
        patterns = self._metadata_patterns()
        where = " AND ".join("qualified_name NOT LIKE ?" for _ in patterns)
        for document in documents:
            row = self.workspace.db.connection.execute(
                f"""SELECT 1 FROM module_snapshots
                    WHERE revision_id = ? AND qualified_name = ? AND {where}""",
                (revision_id, document, *patterns),
            ).fetchone()
            if row is None:
                raise NotFoundError(f"program document {document!r} not found")

    def _tasks(
        self,
        project: str,
        branch: str,
        revision_id: str,
        *,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        pattern = f"{TASK_CONTRACT_PREFIX}%"
        total = int(
            self.workspace.db.connection.execute(
                """SELECT COUNT(*) AS count
                   FROM module_snapshots
                   WHERE revision_id = ? AND qualified_name LIKE ?""",
                (revision_id, pattern),
            ).fetchone()["count"]
        )
        rows = self.workspace.db.connection.execute(
            """SELECT qualified_name, ast_json
               FROM module_snapshots
               WHERE revision_id = ? AND qualified_name LIKE ?
               ORDER BY qualified_name
               LIMIT ?""",
            (revision_id, pattern, limit),
        ).fetchall()
        state = self.workspace._state_at_revision(revision_id)
        result = []
        for row in rows:
            storage_document = str(row["qualified_name"])
            name = storage_document[len(TASK_CONTRACT_PREFIX) :]
            root = json.loads(str(row["ast_json"]))
            config = self.tasks._parse_tree(root, name=name)
            self.tasks._validate_references(state, config, creating=False)
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
        return result, total

    @staticmethod
    def _metadata_patterns() -> tuple[str, ...]:
        return (
            f"{BUILD_TARGET_PREFIX}%",
            f"{TEST_TARGET_PREFIX}%",
            f"{TASK_CONTRACT_PREFIX}%",
        )
