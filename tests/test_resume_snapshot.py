from __future__ import annotations

from pathlib import Path

import pytest

from weave_frontend import NotFoundError, SExpressionWorkspace, ValidationError
from weave_frontend.concurrent_build_targets import BuildTargetRegistry
from weave_frontend.concurrent_merge_policy import MergePolicyRegistry
from weave_frontend.resume_snapshot import (
    MAX_CONTEXT_PREVIEW_CHARS,
    RESUME_SNAPSHOT_FORMAT,
    ResumeSnapshotService,
)

LIBRARY = """(program
  (name \"resume-library\")
  (version \"0.1\"))
"""


def _service(
    workspace: SExpressionWorkspace,
) -> tuple[ResumeSnapshotService, BuildTargetRegistry, MergePolicyRegistry]:
    targets = BuildTargetRegistry(workspace)
    policies = MergePolicyRegistry(workspace)
    return ResumeSnapshotService(workspace, targets, policies), targets, policies


def _build_reviewed_state(
    workspace: SExpressionWorkspace,
) -> tuple[ResumeSnapshotService, str, dict[str, object]]:
    service, targets, policies = _service(workspace)
    workspace.initialize("demo")
    program = workspace.create_program(
        "demo",
        "main",
        "main.weave",
        program_name="resume-snapshot",
    )
    library = workspace.import_program(
        "demo",
        "main",
        "library.weave",
        LIBRARY,
        expected_revision_id=program["revision_id"],
    )
    target = targets.set(
        "demo",
        "main",
        "application",
        "main.weave",
        additional_documents=["library.weave"],
        expected_revision_id=library["revision_id"],
    )
    long_body = "x" * (MAX_CONTEXT_PREVIEW_CHARS + 25)
    context = workspace.add_context(
        "demo",
        "main",
        scope_kind="document",
        scope_name="main.weave",
        title="Long invariant",
        body=long_body,
        expected_revision_id=target["revision_id"],
    )
    policy = policies.set(
        "demo",
        "main",
        require_preflight=True,
        require_affected_validation=True,
        allow_uncovered_documents=False,
        max_affected_targets=5,
        expected_revision_id=context["revision_id"],
    )
    reviewed_revision = str(policy["revision_id"])
    workspace.create_branch_at_revision("demo", "reviewed", reviewed_revision)
    return service, reviewed_revision, program


def test_resume_snapshot_composes_one_exact_reviewed_state(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "resume.db") as workspace:
        service, reviewed_revision, _ = _build_reviewed_state(workspace)

        snapshot = service.snapshot("demo", "main")
        repeated = service.snapshot("demo", "main")

        assert snapshot["format"] == RESUME_SNAPSHOT_FORMAT
        assert snapshot["snapshot_id"] == repeated["snapshot_id"]
        assert snapshot["revision_id"] == reviewed_revision
        assert snapshot["branch_head_revision_id"] == reviewed_revision
        assert snapshot["revision_is_branch_head"] is True
        assert snapshot["revision"]["root_hash"]
        assert [item["document"] for item in snapshot["program_documents"]] == [
            "library.weave",
            "main.weave",
        ]
        assert all(len(item["source_sha256"]) == 64 for item in snapshot["program_documents"])
        assert all(item["source_bytes"] > 0 for item in snapshot["program_documents"])
        assert snapshot["build_targets"] == [
            {
                "name": "application",
                "document": "main.weave",
                "additional_documents": ["library.weave"],
                "compiler_target": "native",
                "root_node_id": snapshot["build_targets"][0]["root_node_id"],
            }
        ]
        assert snapshot["merge_policy"]["max_affected_targets"] == 5
        assert snapshot["merge_policy"]["revision_id"] == reviewed_revision
        assert snapshot["context_count"] == 2
        long_context = [
            item for item in snapshot["contexts"] if item["title"] == "Long invariant"
        ][0]
        assert len(long_context["body_preview"]) == MAX_CONTEXT_PREVIEW_CHARS
        assert long_context["body_truncated"] is True
        assert snapshot["operations"][0]["operation_kind"] == "set_merge_policy"
        assert snapshot["history"]["revisions"][0]["id"] == reviewed_revision
        assert snapshot["branches"] == [
            {"name": "main", "head_revision_id": reviewed_revision},
            {"name": "reviewed", "head_revision_id": reviewed_revision},
        ]
        assert snapshot["reproducible_fork"]["arguments"] == {
            "project": "demo",
            "revision_id": reviewed_revision,
        }
        assert snapshot["build_recovery"]["arguments"] == {
            "project": "demo",
            "revision_id": reviewed_revision,
        }
        assert "not chronological" in snapshot["build_recovery"]["ordering_note"]


def test_historical_snapshot_never_mixes_later_branch_state(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "historical.db") as workspace:
        service, reviewed_revision, program = _build_reviewed_state(workspace)
        policies = MergePolicyRegistry(workspace)
        advanced = workspace.create_form(
            "demo",
            "main",
            "main.weave",
            str(program["node_id"]),
            "advanced",
            expected_revision_id=reviewed_revision,
        )
        latest_policy = policies.set(
            "demo",
            "main",
            require_preflight=True,
            require_affected_validation=True,
            allow_uncovered_documents=False,
            max_affected_targets=3,
            expected_revision_id=advanced["revision_id"],
        )

        historical = service.snapshot(
            "demo",
            "main",
            revision_id=reviewed_revision,
        )
        current = service.snapshot("demo", "main")

        assert historical["branch_head_revision_id"] == latest_policy["revision_id"]
        assert historical["revision_id"] == reviewed_revision
        assert historical["revision_is_branch_head"] is False
        assert historical["merge_policy"]["max_affected_targets"] == 5
        assert current["merge_policy"]["max_affected_targets"] == 3
        historical_main = [
            item for item in historical["program_documents"] if item["document"] == "main.weave"
        ][0]
        current_main = [
            item for item in current["program_documents"] if item["document"] == "main.weave"
        ][0]
        assert historical_main["source_sha256"] != current_main["source_sha256"]
        assert historical["operation_count"] == 1
        assert historical["operations"][0]["operation_kind"] == "set_merge_policy"
        assert current["operations"][0]["operation_kind"] == "set_merge_policy"
        assert historical["context_count"] == 2
        assert current["context_count"] == 3
        assert historical["snapshot_id"] != current["snapshot_id"]


def test_resume_snapshot_reports_bounded_truncation(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "bounded.db") as workspace:
        service, reviewed_revision, _ = _build_reviewed_state(workspace)

        snapshot = service.snapshot(
            "demo",
            "main",
            revision_id=reviewed_revision,
            document_limit=1,
            target_limit=1,
            context_limit=1,
            branch_limit=1,
            history_limit=1,
            operation_limit=1,
        )

        assert snapshot["returned_program_document_count"] == 1
        assert snapshot["program_documents_truncated"] is True
        assert snapshot["returned_build_target_count"] == 1
        assert snapshot["build_targets_truncated"] is False
        assert snapshot["returned_context_count"] == 1
        assert snapshot["contexts_truncated"] is True
        assert snapshot["returned_branch_count"] == 1
        assert snapshot["branches_truncated"] is True
        assert snapshot["history"]["returned_count"] == 1
        assert snapshot["history"]["has_more"] is True
        assert snapshot["history"]["next_revision_id"] is not None
        assert snapshot["returned_operation_count"] == 1
        assert snapshot["operations_truncated"] is False


@pytest.mark.parametrize(
    ("keyword", "value"),
    [
        ("document_limit", 0),
        ("target_limit", 101),
        ("context_limit", True),
        ("branch_limit", "bad"),
        ("history_limit", 51),
        ("operation_limit", -1),
    ],
)
def test_resume_snapshot_validates_all_bounds(
    tmp_path: Path,
    keyword: str,
    value: object,
) -> None:
    with SExpressionWorkspace(tmp_path / f"invalid-{keyword}.db") as workspace:
        service, _, _ = _build_reviewed_state(workspace)

        with pytest.raises(ValidationError) as raised:
            service.snapshot("demo", "main", **{keyword: value})  # type: ignore[arg-type]

        assert raised.value.code == "INVALID_RESUME_SNAPSHOT_LIMIT"


def test_resume_snapshot_rejects_foreign_revision(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "foreign.db") as workspace:
        service, reviewed_revision, _ = _build_reviewed_state(workspace)
        _, foreign_revision = workspace.initialize("other")

        with pytest.raises(NotFoundError, match="does not belong"):
            service.snapshot("demo", "main", revision_id=foreign_revision)

        assert service.snapshot("demo", "main")["revision_id"] == reviewed_revision
