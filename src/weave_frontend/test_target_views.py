"""Verified hashes and bounded public views for behavioral test definitions."""

from __future__ import annotations

from typing import Any

from .errors import ValidationError
from .project_metadata import TEST_TARGET_PREFIX
from .test_targets import TestTargetRegistry

TEST_TARGET_LIST_FORMAT = "weave-test-target-list-v1"
MAX_TEST_TARGET_PAGE_SIZE = 100
DEFAULT_TEST_TARGET_PAGE_SIZE = 50


class VerifiedTestTargetRegistry(TestTargetRegistry):
    """Attach deterministic definition hashes to exact test-target reads and writes."""

    def set(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        result = super().set(*args, **kwargs)
        return self._with_definition_hash(result)

    def get(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        result = super().get(*args, **kwargs)
        return self._with_definition_hash(result)

    def list(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [self._with_definition_hash(item) for item in super().list(*args, **kwargs)]

    def _with_definition_hash(self, result: dict[str, Any]) -> dict[str, Any]:
        revision_id = str(result["revision_id"])
        storage_document = str(result["storage_document"])
        root = self.workspace._state_at_revision(revision_id)[storage_document]
        return {
            **result,
            "definition_hash": self.workspace.db.hash_value(root),
        }


class TestTargetPageService:
    """Return bounded lexical summaries while keeping large bodies behind exact reads."""

    def __init__(self, registry: VerifiedTestTargetRegistry) -> None:
        self.registry = registry
        self.workspace = registry.workspace

    def page(
        self,
        project: str,
        *,
        branch: str = "main",
        revision_id: str | None = None,
        start_after_name: str | None = None,
        limit: int = DEFAULT_TEST_TARGET_PAGE_SIZE,
    ) -> dict[str, Any]:
        self._validate_limit(limit)
        if start_after_name is not None:
            self.registry._validate_name(start_after_name)
        revision = revision_id or self.workspace.branch_head(project, branch)
        self.registry._require_project_revision(project, revision)
        state = self.workspace._state_at_revision(revision)
        names = sorted(
            document[len(TEST_TARGET_PREFIX) :]
            for document in state
            if document.startswith(TEST_TARGET_PREFIX)
        )
        if start_after_name is not None:
            names = [name for name in names if name > start_after_name]
        selected = names[:limit]
        entries = [
            self._summary(
                project,
                branch,
                revision,
                name,
                state[f"{TEST_TARGET_PREFIX}{name}"],
                state,
            )
            for name in selected
        ]
        remaining = len(names) - len(selected)
        return {
            "format": TEST_TARGET_LIST_FORMAT,
            "project": project,
            "branch": branch,
            "revision_id": revision,
            "start_after_name": start_after_name,
            "limit": limit,
            "total_test_target_count": len(
                [
                    document
                    for document in state
                    if document.startswith(TEST_TARGET_PREFIX)
                ]
            ),
            "remaining_after_cursor_count": len(names),
            "returned_test_target_count": len(entries),
            "test_targets_truncated": remaining > 0,
            "next_after_name": selected[-1] if remaining > 0 and selected else None,
            "test_targets": entries,
        }

    def _summary(
        self,
        project: str,
        branch: str,
        revision_id: str,
        name: str,
        root: dict[str, Any],
        state: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        config = self.registry._parse_tree(root, name=name)
        self.registry._require_build_target(state, str(config["build_target"]))
        return {
            "name": name,
            "build_target": config["build_target"],
            "argument_count": len(config["arguments"]),
            "stdin_bytes": len(config["stdin"].encode("utf-8")),
            "expected_exit_code": config["expected_exit_code"],
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

    @staticmethod
    def _validate_limit(limit: Any) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValidationError(
                "INVALID_TEST_TARGET_PAGE_LIMIT",
                "limit must be an integer",
            )
        if limit < 1 or limit > MAX_TEST_TARGET_PAGE_SIZE:
            raise ValidationError(
                "INVALID_TEST_TARGET_PAGE_LIMIT",
                f"limit must be between 1 and {MAX_TEST_TARGET_PAGE_SIZE}",
            )
