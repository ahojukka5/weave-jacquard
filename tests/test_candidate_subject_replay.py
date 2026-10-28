from __future__ import annotations

from pathlib import Path

import pytest

from weave_frontend import SExpressionWorkspace
from weave_frontend.builds import MetadataBuildTargetRegistry
from weave_frontend.compiler import CompilerBridge
from weave_frontend.errors import ArtifactIntegrityError
from weave_frontend.merges import (
    MERGE_PREVIEW_FORMAT,
    MergeCandidateBuildService,
    MetadataMergePreviewService,
)
from weave_frontend.verified_merge_candidate_build import (
    MergeCandidateBuildService as ProductionCandidateBuildService,
)


@pytest.fixture(params=[MergeCandidateBuildService, ProductionCandidateBuildService])
def captured_candidate(tmp_path: Path, request: pytest.FixtureRequest):
    with SExpressionWorkspace(tmp_path / "subject.db") as workspace:
        _, initial = workspace.initialize("demo")
        program = workspace.create_program(
            "demo",
            "main",
            "main.weave",
            program_name="subject",
            expected_revision_id=initial,
        )
        workspace.create_branch("demo", "feature", expected_revision_id=program["revision_id"])
        previews = MetadataMergePreviewService(workspace)
        candidate = previews.candidate("demo", "main", "feature")
        builds = request.param(
            previews,
            MetadataBuildTargetRegistry(workspace),
            CompilerBridge(workspace, build_root=tmp_path / "builds"),
        )
        yield workspace, builds, candidate


def test_current_preview_replays_after_branch_heads_move(captured_candidate) -> None:
    workspace, builds, candidate = captured_candidate
    subject = builds._subject(candidate)
    workspace.create_program(
        "demo",
        "feature",
        "later.weave",
        program_name="later",
        expected_revision_id=subject["source_head_revision_id"],
    )
    assert (
        builds.previews.candidate("demo", "main", "feature")["preview_id"] != subject["preview_id"]
    )
    assert builds._reconstruct_subject_state(subject) == candidate["_merged_state"]


def test_pre_ancestry_v1_subject_keeps_its_immutable_identity(captured_candidate) -> None:
    workspace, builds, candidate = captured_candidate
    subject = builds._subject(candidate)
    original_payload = {
        "format": MERGE_PREVIEW_FORMAT,
        **{
            key: subject[key]
            for key in (
                "project",
                "target_branch",
                "source_branch",
                "base_revision_id",
                "target_head_revision_id",
                "source_head_revision_id",
            )
        },
    }
    subject["preview_id"] = workspace.db.hash_value(original_payload)
    assert builds._reconstruct_subject_state(subject) == candidate["_merged_state"]


@pytest.mark.parametrize("field", ["preview_id", "merged_root_hash"])
def test_corrupt_subject_identity_is_rejected(captured_candidate, field: str) -> None:
    _, builds, candidate = captured_candidate
    subject = builds._subject(candidate)
    subject[field] = "0" * 64
    with pytest.raises(ArtifactIntegrityError):
        builds._reconstruct_subject_state(subject)
