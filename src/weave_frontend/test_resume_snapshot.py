"""Resume snapshots extended with revisioned behavioral test definitions."""

from __future__ import annotations

from typing import Any

from .checkpoint_resume_snapshot import CheckpointResumeSnapshotService
from .errors import NotFoundError
from .project_metadata import BUILD_TARGET_PREFIX, TEST_TARGET_PREFIX
from .test_targets import TestTargetRegistry

MAX_RESUME_TEST_TARGETS = 100


class TestResumeSnapshotService(CheckpointResumeSnapshotService):
    """Compose exact program, checkpoint, and bounded behavioral-test orientation."""

    def __init__(
        self,
        workspace: Any,
        targets: Any,
        policies: Any,
        checkpoints: Any,
        tests: TestTargetRegistry,
    ) -> None:
        super().__init__(workspace, targets, policies, checkpoints)
        self.tests = tests

    def snapshot(
        self,
        project: str,
        branch: str = "main",
        *,
        test_target_limit: int = 50,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self._validate_limit(
            "test_target_limit",
            test_target_limit,
            MAX_RESUME_TEST_TARGETS,
        )
        result = super().snapshot(project, branch, **kwargs)
        revision_id = str(result["revision_id"])
        entries, total = self._tests(
            project,
            branch,
            revision_id,
            limit=test_target_limit,
        )
        result.pop("snapshot_id")
        result["limits"]["test_target_limit"] = test_target_limit
        result["test_target_count"] = total
        result["returned_test_target_count"] = len(entries)
        result["test_targets_truncated"] = len(entries) < total
        result["test_targets"] = entries
        result["test_recovery"] = {
            "tool": "test_target_list",
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
        names = [
            name
            for name in self._program_document_names(modules)
            if not name.startswith(TEST_TARGET_PREFIX)
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
        for document in documents:
            if (
                document not in modules
                or document.startswith(BUILD_TARGET_PREFIX)
                or document.startswith(TEST_TARGET_PREFIX)
            ):
                raise NotFoundError(f"program document {document!r} not found")

    def _tests(
        self,
        project: str,
        branch: str,
        revision_id: str,
        *,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        modules = self._revision_modules(revision_id)
        names = sorted(name for name in modules if name.startswith(TEST_TARGET_PREFIX))
        page = names[:limit]
        result: list[dict[str, Any]] = []
        for storage_document in page:
            name = storage_document[len(TEST_TARGET_PREFIX) :]
            root = modules[storage_document]
            config = self.tests._parse_tree(root, name=name)
            self.tests._require_build_target(modules, config["build_target"])
            result.append(
                {
                    "name": name,
                    "build_target": config["build_target"],
                    "argument_count": len(config["arguments"]),
                    "expected_exit_code": config["expected_exit_code"],
                    "stdin_bytes": len(config["stdin"].encode("utf-8")),
                    "expected_stdout_bytes": len(config["expected_stdout"].encode("utf-8")),
                    "expected_stderr_bytes": len(config["expected_stderr"].encode("utf-8")),
                    "timeout_ms": config["timeout_ms"],
                    "max_memory_bytes": config["max_memory_bytes"],
                    "max_output_bytes": config["max_output_bytes"],
                    "max_file_bytes": config["max_file_bytes"],
                    "network_policy": config["network_policy"],
                    "filesystem_policy": config["filesystem_policy"],
                    "tags": config["tags"],
                    "root_node_id": root["id"],
                    "definition_hash": self.workspace.db.hash_value(root),
                    "detail": {
                        "tool": "test_target_get",
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
