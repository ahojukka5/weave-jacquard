from __future__ import annotations

from weave_frontend.merge_preview import MergePreviewService
from weave_frontend.metadata_build_targets import BuildTargetRegistry
from weave_frontend.metadata_merge_impact import MergeTargetImpactService
from weave_frontend.project_metadata import TEST_TARGET_PREFIX
from weave_frontend.test_targets import TestTargetRegistry as _TestTargetRegistry


def test_test_definition_only_merge_is_not_compiler_source_impact(
    sexpr_workspace,
) -> None:
    program = sexpr_workspace.create_program(
        "sexpr-demo",
        "main",
        "main.weave",
        program_name="test-metadata-impact",
    )
    targets = BuildTargetRegistry(sexpr_workspace)
    target = targets.set(
        "sexpr-demo",
        "main",
        "application",
        "main.weave",
        expected_revision_id=program["revision_id"],
    )
    sexpr_workspace.create_branch("sexpr-demo", "target", from_branch="main")
    sexpr_workspace.create_branch("sexpr-demo", "source", from_branch="main")
    source_test = _TestTargetRegistry(sexpr_workspace).set(
        "sexpr-demo",
        "source",
        "smoke",
        "application",
        expected_revision_id=target["revision_id"],
    )

    result = MergeTargetImpactService(
        MergePreviewService(sexpr_workspace),
        targets,
    ).analyze("sexpr-demo", "target", "source")

    assert result["source_head_revision_id"] == source_test["revision_id"]
    assert result["changed_program_documents"] == []
    assert result["changed_target_documents"] == []
    assert result["changed_test_documents"] == [f"{TEST_TARGET_PREFIX}smoke"]
    assert result["candidate_covered_changed_documents"] == []
    assert result["uncovered_changed_documents"] == []
    assert result["total_affected_target_count"] == 0
    assert result["affected_targets"] == []
