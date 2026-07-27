from __future__ import annotations

from pathlib import Path

import pytest

from weave_frontend import SExpressionWorkspace, ValidationError
from weave_frontend.metadata_build_targets import BuildTargetRegistry
from weave_frontend.metadata_merge_preview import MergePreviewService
from weave_frontend.test_targets import TestTargetRegistry


def _base_state(
    workspace: SExpressionWorkspace,
) -> tuple[BuildTargetRegistry, TestTargetRegistry, str]:
    workspace.initialize("demo")
    program = workspace.create_program(
        "demo",
        "main",
        "main.weave",
        program_name="test-references",
    )
    targets = BuildTargetRegistry(workspace)
    target = targets.set(
        "demo",
        "main",
        "application",
        "main.weave",
        expected_revision_id=program["revision_id"],
    )
    return targets, TestTargetRegistry(workspace), str(target["revision_id"])


def test_build_target_delete_is_blocked_until_tests_are_removed(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "target-in-use.db") as workspace:
        targets, tests, target_revision = _base_state(workspace)
        test = tests.set(
            "demo",
            "main",
            "smoke",
            "application",
            expected_revision_id=target_revision,
        )

        with pytest.raises(ValidationError) as raised:
            targets.delete(
                "demo",
                "main",
                "application",
                expected_revision_id=test["revision_id"],
            )

        assert raised.value.code == "BUILD_TARGET_IN_USE"
        assert "smoke" in raised.value.message
        assert workspace.branch_head("demo", "main") == test["revision_id"]

        removed_test = tests.delete(
            "demo",
            "main",
            "smoke",
            expected_revision_id=test["revision_id"],
        )
        removed_target = targets.delete(
            "demo",
            "main",
            "application",
            expected_revision_id=removed_test["revision_id"],
        )
        assert targets.list("demo") == []
        assert removed_target["base_revision_id"] == removed_test["revision_id"]


def test_merge_preview_rejects_cross_branch_dangling_test_reference(
    tmp_path: Path,
) -> None:
    with SExpressionWorkspace(tmp_path / "merge-reference.db") as workspace:
        targets, tests, base_revision = _base_state(workspace)
        workspace.create_branch_at_revision("demo", "target", base_revision)
        workspace.create_branch_at_revision("demo", "source", base_revision)
        target_test = tests.set(
            "demo",
            "target",
            "smoke",
            "application",
            expected_revision_id=base_revision,
        )
        source_delete = targets.delete(
            "demo",
            "source",
            "application",
            expected_revision_id=base_revision,
        )
        preview = MergePreviewService(workspace)

        with pytest.raises(ValidationError) as raised:
            preview.preview("demo", "target", "source")
        assert raised.value.code == "INVALID_TEST_TARGET_REFERENCE"
        assert "smoke" in raised.value.message

        with pytest.raises(ValidationError) as direct_merge:
            preview.merge("demo", "target", "source")
        assert direct_merge.value.code == "INVALID_TEST_TARGET_REFERENCE"
        assert workspace.branch_head("demo", "target") == target_test["revision_id"]
        assert workspace.branch_head("demo", "source") == source_delete["revision_id"]
