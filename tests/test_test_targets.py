from __future__ import annotations

from pathlib import Path

import pytest

from weave_frontend import SExpressionWorkspace, ValidationError
from weave_frontend.errors import NotFoundError
from weave_frontend.metadata_build_targets import BuildTargetRegistry
from weave_frontend.project_metadata import TEST_TARGET_PREFIX
from weave_frontend.test_targets import (
    MAX_TEST_ARGUMENTS,
    MAX_TEST_TIMEOUT_MS,
    TestTargetRegistry,
)


def _workspace_with_target(
    path: Path,
) -> tuple[SExpressionWorkspace, BuildTargetRegistry, TestTargetRegistry, str]:
    workspace = SExpressionWorkspace(path)
    workspace.initialize("demo")
    program = workspace.create_program(
        "demo",
        "main",
        "main.weave",
        program_name="test-targets",
    )
    targets = BuildTargetRegistry(workspace)
    target = targets.set(
        "demo",
        "main",
        "application",
        "main.weave",
        expected_revision_id=program["revision_id"],
    )
    return workspace, targets, TestTargetRegistry(workspace), target["revision_id"]


def _counts(workspace: SExpressionWorkspace) -> tuple[int, int]:
    revision_count = workspace.db.connection.execute(
        "SELECT COUNT(*) AS count FROM revisions"
    ).fetchone()["count"]
    operation_count = workspace.db.connection.execute(
        "SELECT COUNT(*) AS count FROM operations"
    ).fetchone()["count"]
    return int(revision_count), int(operation_count)


def test_set_update_and_historical_reads_preserve_identity(tmp_path: Path) -> None:
    workspace, _, tests, base_revision = _workspace_with_target(tmp_path / "tests.db")
    with workspace:
        created = tests.set(
            "demo",
            "main",
            "cli-smoke",
            "application",
            arguments=["--count", "3"],
            stdin="input\n",
            expected_exit_code=7,
            expected_stdout="done\n",
            expected_stderr="warning\n",
            timeout_ms=2_000,
            max_memory_bytes=32 * 1024 * 1024,
            max_output_bytes=8_192,
            max_file_bytes=4_096,
            tags=["smoke", "cli/fast"],
            expected_revision_id=base_revision,
        )

        assert created["base_revision_id"] == base_revision
        assert created["network_policy"] == "deny"
        assert created["filesystem_policy"] == "isolated"
        assert created["storage_document"] == f"{TEST_TARGET_PREFIX}cli-smoke"

        updated = tests.set(
            "demo",
            "main",
            "cli-smoke",
            "application",
            arguments=["--count", "4"],
            expected_stdout="updated\n",
            tags=["smoke"],
            expected_revision_id=created["revision_id"],
        )
        assert updated["base_revision_id"] == created["revision_id"]
        assert updated["root_node_id"] == created["root_node_id"]

        historical = tests.get(
            "demo",
            "cli-smoke",
            revision_id=created["revision_id"],
        )
        current = tests.get("demo", "cli-smoke")

        assert historical["arguments"] == ["--count", "3"]
        assert historical["expected_stdout"] == "done\n"
        assert historical["tags"] == ["smoke", "cli/fast"]
        assert current["arguments"] == ["--count", "4"]
        assert current["expected_stdout"] == "updated\n"
        assert current["tags"] == ["smoke"]
        assert tests.list("demo") == [current]

        operations = workspace.db.connection.execute(
            """SELECT operation_kind, target FROM operations
               WHERE revision_id IN (?, ?) ORDER BY rowid""",
            (created["revision_id"], updated["revision_id"]),
        ).fetchall()
        assert [tuple(row) for row in operations] == [
            ("set_test_target", f"{TEST_TARGET_PREFIX}cli-smoke"),
            ("set_test_target", f"{TEST_TARGET_PREFIX}cli-smoke"),
        ]


def test_stale_writes_and_delete_are_atomic(tmp_path: Path) -> None:
    workspace, _, tests, base_revision = _workspace_with_target(
        tmp_path / "test-stale.db"
    )
    with workspace:
        created = tests.set(
            "demo",
            "main",
            "smoke",
            "application",
            expected_revision_id=base_revision,
        )
        counts = _counts(workspace)

        with pytest.raises(ValidationError) as raised:
            tests.set(
                "demo",
                "main",
                "stale",
                "application",
                expected_revision_id=base_revision,
            )
        assert raised.value.code == "STALE_BRANCH_HEAD"
        assert _counts(workspace) == counts
        assert [item["name"] for item in tests.list("demo")] == ["smoke"]

        deleted = tests.delete(
            "demo",
            "main",
            "smoke",
            expected_revision_id=created["revision_id"],
        )
        assert deleted["base_revision_id"] == created["revision_id"]
        assert tests.list("demo") == []
        assert tests.get(
            "demo",
            "smoke",
            revision_id=created["revision_id"],
        )["name"] == "smoke"


def test_test_definition_validation_is_bounded(tmp_path: Path) -> None:
    workspace, _, tests, base_revision = _workspace_with_target(
        tmp_path / "test-validation.db"
    )
    with workspace:
        with pytest.raises(NotFoundError, match="build target"):
            tests.set("demo", "main", "missing", "does-not-exist")

        invalid_cases = [
            {"name": "bad name", "build_target": "application"},
            {
                "name": "too-many-args",
                "build_target": "application",
                "arguments": ["x"] * (MAX_TEST_ARGUMENTS + 1),
            },
            {
                "name": "timeout",
                "build_target": "application",
                "timeout_ms": MAX_TEST_TIMEOUT_MS + 1,
            },
            {
                "name": "duplicate-tags",
                "build_target": "application",
                "tags": ["smoke", "smoke"],
            },
        ]
        for case in invalid_cases:
            with pytest.raises(ValidationError):
                tests.set(
                    "demo",
                    "main",
                    expected_revision_id=base_revision,
                    **case,
                )

        assert workspace.branch_head("demo", "main") == base_revision
        assert tests.list("demo") == []


def test_reserved_test_metadata_never_enters_build_source_sets(tmp_path: Path) -> None:
    workspace, targets, tests, base_revision = _workspace_with_target(
        tmp_path / "test-sources.db"
    )
    with workspace:
        test = tests.set(
            "demo",
            "main",
            "smoke",
            "application",
            expected_revision_id=base_revision,
        )

        assert targets.program_documents("demo") == ["main.weave"]
        with pytest.raises(ValidationError) as raised:
            targets.set(
                "demo",
                "main",
                "invalid",
                f"{TEST_TARGET_PREFIX}smoke",
                expected_revision_id=test["revision_id"],
            )
        assert raised.value.code == "INVALID_BUILD_DOCUMENT"
