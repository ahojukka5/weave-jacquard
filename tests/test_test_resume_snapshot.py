from __future__ import annotations

from pathlib import Path

import pytest

from weave_frontend import SExpressionWorkspace, ValidationError
from weave_frontend.agent_checkpoint import AgentCheckpointRegistry
from weave_frontend.concurrent_merge_policy import MergePolicyRegistry
from weave_frontend.metadata_build_targets import BuildTargetRegistry
from weave_frontend.test_resume_snapshot import MAX_RESUME_TEST_TARGETS
from weave_frontend.test_resume_snapshot import (
    TestResumeSnapshotService as _TestResumeSnapshotService,
)
from weave_frontend.test_targets import TestTargetRegistry as _TestTargetRegistry


def _service(workspace: SExpressionWorkspace) -> _TestResumeSnapshotService:
    targets = BuildTargetRegistry(workspace)
    tests = _TestTargetRegistry(workspace)
    return _TestResumeSnapshotService(
        workspace,
        targets,
        MergePolicyRegistry(workspace),
        AgentCheckpointRegistry(workspace),
        tests,
    )


def test_resume_snapshot_separates_programs_and_bounded_test_summaries(
    tmp_path: Path,
) -> None:
    with SExpressionWorkspace(tmp_path / "test-resume.db") as workspace:
        workspace.initialize("demo")
        program = workspace.create_program(
            "demo",
            "main",
            "main.weave",
            program_name="test-resume",
        )
        targets = BuildTargetRegistry(workspace)
        target = targets.set(
            "demo",
            "main",
            "application",
            "main.weave",
            expected_revision_id=program["revision_id"],
        )
        tests = _TestTargetRegistry(workspace)
        first = tests.set(
            "demo",
            "main",
            "alpha",
            "application",
            arguments=["--alpha"],
            stdin="input",
            expected_stdout="large result",
            tags=["smoke"],
            expected_revision_id=target["revision_id"],
        )
        second = tests.set(
            "demo",
            "main",
            "beta",
            "application",
            expected_exit_code=2,
            expected_revision_id=first["revision_id"],
        )
        service = _service(workspace)

        snapshot = service.snapshot("demo", "main", test_target_limit=1)
        repeated = service.snapshot("demo", "main", test_target_limit=1)

        assert snapshot["snapshot_id"] == repeated["snapshot_id"]
        assert snapshot["revision_id"] == second["revision_id"]
        assert snapshot["program_document_count"] == 1
        assert [item["document"] for item in snapshot["program_documents"]] == [
            "main.weave"
        ]
        assert snapshot["test_target_count"] == 2
        assert snapshot["returned_test_target_count"] == 1
        assert snapshot["test_targets_truncated"] is True
        assert snapshot["limits"]["test_target_limit"] == 1
        alpha_root = workspace._state_at_revision(second["revision_id"])[
            "@test-target/alpha"
        ]
        assert snapshot["test_targets"] == [
            {
                "name": "alpha",
                "build_target": "application",
                "argument_count": 1,
                "expected_exit_code": 0,
                "stdin_bytes": 5,
                "expected_stdout_bytes": 12,
                "expected_stderr_bytes": 0,
                "timeout_ms": 5_000,
                "max_memory_bytes": 256 * 1024 * 1024,
                "max_output_bytes": 64 * 1024,
                "max_file_bytes": 1024 * 1024,
                "network_policy": "deny",
                "filesystem_policy": "isolated",
                "tags": ["smoke"],
                "root_node_id": alpha_root["id"],
                "definition_hash": workspace.db.hash_value(alpha_root),
                "detail": {
                    "tool": "test_target_get",
                    "arguments": {
                        "project": "demo",
                        "name": "alpha",
                        "branch": "main",
                        "revision_id": second["revision_id"],
                    },
                },
            }
        ]
        assert snapshot["test_recovery"]["arguments"]["revision_id"] == second[
            "revision_id"
        ]
        assert "expected_stdout" not in snapshot["test_targets"][0]

        before_tests = service.snapshot(
            "demo",
            "main",
            revision_id=target["revision_id"],
        )
        assert before_tests["test_target_count"] == 0
        assert before_tests["test_targets"] == []


def test_resume_snapshot_validates_test_target_limit(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "test-resume-limit.db") as workspace:
        workspace.initialize("demo")
        service = _service(workspace)

        with pytest.raises(ValidationError) as raised:
            service.snapshot(
                "demo",
                "main",
                test_target_limit=MAX_RESUME_TEST_TARGETS + 1,
            )

        assert raised.value.code == "INVALID_RESUME_SNAPSHOT_LIMIT"
