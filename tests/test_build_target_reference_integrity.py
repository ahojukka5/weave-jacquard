from __future__ import annotations

from pathlib import Path

import pytest

from weave_frontend import SExpressionWorkspace, ValidationError
from weave_frontend.builds import MetadataBuildTargetRegistry as BuildTargetRegistry
from weave_frontend.builds import (
    build_target_references,
    validate_build_target_references,
)
from weave_frontend.metadata_merge_preview import MergePreviewService


def _workspace(path: Path) -> tuple[SExpressionWorkspace, str]:
    workspace = SExpressionWorkspace(path)
    _, initial_revision = workspace.initialize("demo")
    program = workspace.create_program(
        "demo",
        "main",
        "main.weave",
        program_name="build-target-integrity",
        expected_revision_id=initial_revision,
    )
    return workspace, str(program["revision_id"])


def test_build_target_reference_validation_accepts_exact_program_bindings(
    tmp_path: Path,
) -> None:
    workspace, program_revision = _workspace(tmp_path / "valid.db")
    targets = BuildTargetRegistry(workspace)
    with workspace:
        target = targets.set(
            "demo",
            "main",
            "application",
            "main.weave",
            expected_revision_id=program_revision,
        )
        state = workspace._state_at_revision(str(target["revision_id"]))
        assert build_target_references(state) == {"main.weave": ["application"]}
        validate_build_target_references(state)


def test_build_target_reference_validation_rejects_missing_program(
    tmp_path: Path,
) -> None:
    workspace, program_revision = _workspace(tmp_path / "missing.db")
    targets = BuildTargetRegistry(workspace)
    with workspace:
        target = targets.set(
            "demo",
            "main",
            "application",
            "main.weave",
            expected_revision_id=program_revision,
        )
        state = workspace._state_at_revision(str(target["revision_id"]))
        del state["main.weave"]
        with pytest.raises(ValidationError) as raised:
            validate_build_target_references(state)
        assert raised.value.code == "INVALID_BUILD_TARGET_DOCUMENT_REFERENCE"


def test_merge_preview_rejects_dangling_build_target_after_source_deletion(
    tmp_path: Path,
) -> None:
    workspace, program_revision = _workspace(tmp_path / "merge.db")
    targets = BuildTargetRegistry(workspace)
    previews = MergePreviewService(workspace)
    with workspace:
        workspace.create_branch_at_revision("demo", "delete-source", program_revision)
        target = targets.set(
            "demo",
            "main",
            "application",
            "main.weave",
            expected_revision_id=program_revision,
        )
        deleted = workspace._commit(
            "demo",
            "delete-source",
            {},
            message="delete program main.weave",
            author="test-agent",
            operations=[("delete_program", "main.weave", {})],
            expected_branch_heads={"delete-source": program_revision},
        )
        assert workspace.branch_head("demo", "delete-source") == deleted
        assert workspace.branch_head("demo", "main") == target["revision_id"]

        with pytest.raises(ValidationError) as raised:
            previews.preview("demo", "main", "delete-source")
        assert raised.value.code == "INVALID_BUILD_TARGET_DOCUMENT_REFERENCE"
        assert workspace.branch_head("demo", "main") == target["revision_id"]
