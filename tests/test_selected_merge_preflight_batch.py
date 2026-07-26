from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from weave_frontend import SExpressionWorkspace, ValidationError
from weave_frontend.agent_checkpoint import AgentCheckpointRegistry
from weave_frontend.errors import ConflictError
from weave_frontend.merge_preview import MergePreviewService
from weave_frontend.project_agent_status import ProjectAgentStatusService
from weave_frontend.project_merge_queue import ProjectMergeQueueService
from weave_frontend.selected_merge_preflight_batch import (
    MAX_SELECTED_MERGE_PREFLIGHT_DOCUMENTS,
    MAX_SELECTED_MERGE_PREFLIGHT_SOURCES,
    SELECTED_MERGE_PREFLIGHT_BATCH_FORMAT,
    SelectedMergePreflightBatchService,
)


def _batch_state(
    workspace: SExpressionWorkspace,
) -> tuple[ProjectMergeQueueService, dict[str, Any]]:
    workspace.initialize("demo")
    program = workspace.create_program(
        "demo",
        "main",
        "main.weave",
        program_name="selected-preflight",
    )
    conflict_atom = workspace.add_atom(
        "demo",
        "main",
        "main.weave",
        str(program["node_id"]),
        "string",
        "conflict",
        expected_revision_id=program["revision_id"],
    )
    clean_atom = workspace.add_atom(
        "demo",
        "main",
        "main.weave",
        str(program["node_id"]),
        "string",
        "clean",
        expected_revision_id=conflict_atom["revision_id"],
    )
    base_revision = str(clean_atom["revision_id"])
    for branch in ("conflict", "not-ready", "policy-error", "ready", "unselected"):
        workspace.create_branch_at_revision("demo", branch, base_revision)

    ready = workspace.set_atom(
        "demo",
        "ready",
        "main.weave",
        str(clean_atom["node_id"]),
        "ready-change",
        expected_revision_id=base_revision,
    )
    not_ready = workspace.create_form(
        "demo",
        "not-ready",
        "main.weave",
        str(program["node_id"]),
        "not-ready-change",
        expected_revision_id=base_revision,
    )
    policy_error = workspace.create_form(
        "demo",
        "policy-error",
        "main.weave",
        str(program["node_id"]),
        "policy-error-change",
        expected_revision_id=base_revision,
    )
    conflict_source = workspace.set_atom(
        "demo",
        "conflict",
        "main.weave",
        str(conflict_atom["node_id"]),
        "source-conflict",
        expected_revision_id=base_revision,
    )
    target = workspace.set_atom(
        "demo",
        "main",
        "main.weave",
        str(conflict_atom["node_id"]),
        "target-conflict",
        expected_revision_id=base_revision,
    )

    previews = MergePreviewService(workspace)
    statuses = ProjectAgentStatusService(AgentCheckpointRegistry(workspace))
    queues = ProjectMergeQueueService(previews, statuses)
    catalog = queues.page("demo", limit=10)["catalog_id"]
    return queues, {
        "program": program,
        "base_revision": base_revision,
        "ready": ready,
        "not_ready": not_ready,
        "policy_error": policy_error,
        "conflict_source": conflict_source,
        "target": target,
        "catalog_id": catalog,
    }


class _FakePreflights:
    def __init__(self, previews: MergePreviewService) -> None:
        self.previews = previews
        self.calls: list[tuple[str, bool]] = []

    def run(
        self,
        project: str,
        target_branch: str,
        source_branch: str,
        *,
        preview_id: str | None = None,
        allow_uncovered_documents: bool = False,
    ) -> dict[str, Any]:
        self.calls.append((source_branch, allow_uncovered_documents))
        preview = self.previews.preview(project, target_branch, source_branch)
        assert preview_id == preview["preview_id"]
        if source_branch == "conflict":
            raise ConflictError(list(preview["conflicts"]))
        if source_branch == "policy-error":
            raise ValidationError(
                "MERGE_POLICY_VIOLATION",
                "target policy forbids this override",
            )

        ready = source_branch == "ready"
        records = [
            {
                "target": "application",
                "validation_id": f"validation-{source_branch}-application",
                "available": True,
                "valid": True,
                "returncode": 0,
                "timed_out": False,
                "diagnostic": None,
                "compiler_sha256": "a" * 64,
                "wir_sha256": "b" * 64,
                "wir_bytes": 100,
            },
            {
                "target": "mirror",
                "validation_id": f"validation-{source_branch}-mirror",
                "available": True,
                "valid": ready,
                "returncode": 0 if ready else 11,
                "timed_out": False,
                "diagnostic": None if ready else "fake failure",
                "compiler_sha256": "a" * 64,
                "wir_sha256": "c" * 64 if ready else None,
                "wir_bytes": 120 if ready else 0,
            },
        ]
        passed = [record["target"] for record in records if record["valid"]]
        failed = [record["target"] for record in records if not record["valid"]]
        validation_set = {
            "coverage_passed": True,
            "affected_surviving_target_count": 2,
            "validated_target_count": 2,
            "passed_target_count": len(passed),
            "failed_target_count": len(failed),
            "unavailable_target_count": 0,
            "passed_targets": passed,
            "failed_targets": failed,
            "unavailable_targets": [],
            "target_validations": records,
        }
        return {
            "preflight_id": f"preflight-{source_branch}",
            "preview_id": preview["preview_id"],
            "base_revision_id": preview["base_revision_id"],
            "target_head_revision_id": preview["target_head_revision_id"],
            "source_head_revision_id": preview["source_head_revision_id"],
            "merged_root_hash": preview["merged_root_hash"],
            "ready_for_publication": ready,
            "impact": {
                "changed_program_documents": ["lib.weave", "main.weave"],
                "uncovered_changed_documents": [],
                "total_affected_target_count": 2,
            },
            "impact_targets_truncated": False,
            "validation_set": validation_set,
            "target_merge_policy": {"policy_hash": "target-policy"},
            "source_merge_policy": {"policy_hash": f"source-{source_branch}"},
            "source_policy_ignored": True,
            "publication_tool": "branch_merge",
            "publication_arguments": {
                "project": project,
                "target_branch": target_branch,
                "source_branch": source_branch,
                "preview_id": preview["preview_id"],
                "preflight_id": f"preflight-{source_branch}",
                "validate_affected_targets": True,
                "allow_uncovered_documents": allow_uncovered_documents,
            },
        }


def test_selected_batch_returns_independent_compact_results_in_caller_order(
    tmp_path: Path,
) -> None:
    with SExpressionWorkspace(tmp_path / "batch.db") as workspace:
        queues, state = _batch_state(workspace)
        fake = _FakePreflights(queues.previews)
        service = SelectedMergePreflightBatchService(queues, fake)  # type: ignore[arg-type]

        result = service.run(
            "demo",
            "main",
            ["ready", "not-ready", "conflict", "policy-error"],
            str(state["catalog_id"]),
            allow_uncovered_sources=["ready", "policy-error"],
            validation_result_limit=1,
            document_limit=1,
        )
        repeated = service.run(
            "demo",
            "main",
            ["ready", "not-ready", "conflict", "policy-error"],
            str(state["catalog_id"]),
            allow_uncovered_sources=["ready", "policy-error"],
            validation_result_limit=1,
            document_limit=1,
        )

        assert result["format"] == SELECTED_MERGE_PREFLIGHT_BATCH_FORMAT
        assert result["batch_id"] == repeated["batch_id"]
        assert result["target_head_revision_id"] == state["target"]["revision_id"]
        assert result["selected_source_count"] == 4
        assert result["completed_source_count"] == 2
        assert result["error_source_count"] == 2
        assert result["ready_source_count"] == 1
        assert result["not_ready_source_count"] == 1
        assert result["allow_uncovered_sources"] == ["policy-error", "ready"]
        assert [entry["source_branch"] for entry in result["sources"]] == [
            "ready",
            "not-ready",
            "conflict",
            "policy-error",
        ]
        assert "explicit selected sources" in result["execution_note"]
        assert "does not itself express priority" in result["ordering_note"]

        ready = result["sources"][0]
        assert ready["status"] == "completed"
        assert ready["ready_for_publication"] is True
        assert ready["allow_uncovered_documents"] is True
        assert ready["changed_program_document_count"] == 2
        assert ready["changed_program_documents"] == ["lib.weave"]
        assert ready["changed_program_documents_truncated"] is True
        assert ready["validated_target_count"] == 2
        assert ready["returned_target_validation_count"] == 1
        assert ready["target_validations_truncated"] is True
        assert ready["target_validations"][0]["target"] == "application"
        assert ready["publication_arguments"]["preflight_id"] == "preflight-ready"
        assert ready["full_preflight"] == {
            "tool": "branch_merge_preflight",
            "arguments": {
                "project": "demo",
                "target_branch": "main",
                "source_branch": "ready",
                "preview_id": ready["preview_id"],
                "allow_uncovered_documents": True,
            },
        }

        not_ready = result["sources"][1]
        assert not_ready["status"] == "completed"
        assert not_ready["ready_for_publication"] is False
        assert not_ready["failed_target_count"] == 1
        assert not_ready["failed_targets"] == ["mirror"]

        conflict = result["sources"][2]
        assert conflict["status"] == "error"
        assert conflict["ready_for_publication"] is False
        assert conflict["error"]["code"] == "MERGE_CONFLICT"
        assert conflict["error"]["conflicts"]

        policy = result["sources"][3]
        assert policy["status"] == "error"
        assert policy["error"]["code"] == "MERGE_POLICY_VIOLATION"
        assert policy["allow_uncovered_documents"] is True
        assert fake.calls[:4] == [
            ("ready", True),
            ("not-ready", False),
            ("conflict", False),
            ("policy-error", True),
        ]


def test_selected_batch_rejects_stale_catalog_before_execution(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "stale.db") as workspace:
        queues, state = _batch_state(workspace)
        service = SelectedMergePreflightBatchService(
            queues,
            _FakePreflights(queues.previews),  # type: ignore[arg-type]
        )
        workspace.create_form(
            "demo",
            "ready",
            "main.weave",
            str(state["program"]["node_id"]),
            "later",
            expected_revision_id=state["ready"]["revision_id"],
        )

        with pytest.raises(ValidationError) as raised:
            service.run("demo", "main", ["ready"], str(state["catalog_id"]))

        assert raised.value.code == "STALE_SELECTED_PREFLIGHT_CATALOG"


def test_selected_batch_rechecks_whole_catalog_after_compilation(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "race.db") as workspace:
        queues, state = _batch_state(workspace)

        class _MutatingPreflights(_FakePreflights):
            def run(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
                result = super().run(*args, **kwargs)
                workspace.create_program(
                    "demo",
                    "unselected",
                    "race.weave",
                    program_name="race",
                    expected_revision_id=workspace.branch_head("demo", "unselected"),
                )
                return result

        service = SelectedMergePreflightBatchService(
            queues,
            _MutatingPreflights(queues.previews),  # type: ignore[arg-type]
        )

        with pytest.raises(ValidationError) as raised:
            service.run("demo", "main", ["ready"], str(state["catalog_id"]))

        assert raised.value.code == "STALE_SELECTED_PREFLIGHT_CATALOG"


@pytest.mark.parametrize(
    ("sources", "allowed", "code"),
    [
        ([], None, "INVALID_SELECTED_PREFLIGHT_SOURCES"),
        (["ready", "ready"], None, "INVALID_SELECTED_PREFLIGHT_SOURCES"),
        (["ready"] * (MAX_SELECTED_MERGE_PREFLIGHT_SOURCES + 1), None, "INVALID_SELECTED_PREFLIGHT_SOURCES"),
        (["ready"], ["missing"], "INVALID_SELECTED_PREFLIGHT_OVERRIDES"),
        (["ready"], ["ready", "ready"], "INVALID_SELECTED_PREFLIGHT_OVERRIDES"),
    ],
)
def test_selected_batch_validates_sources_and_overrides(
    tmp_path: Path,
    sources: list[str],
    allowed: list[str] | None,
    code: str,
) -> None:
    with SExpressionWorkspace(tmp_path / f"invalid-{code}.db") as workspace:
        queues, state = _batch_state(workspace)
        service = SelectedMergePreflightBatchService(
            queues,
            _FakePreflights(queues.previews),  # type: ignore[arg-type]
        )

        with pytest.raises(ValidationError) as raised:
            service.run(
                "demo",
                "main",
                sources,
                str(state["catalog_id"]),
                allow_uncovered_sources=allowed,
            )

        assert raised.value.code == code


@pytest.mark.parametrize(
    ("keyword", "value"),
    [
        ("validation_result_limit", 0),
        ("validation_result_limit", 65),
        ("document_limit", True),
        ("document_limit", MAX_SELECTED_MERGE_PREFLIGHT_DOCUMENTS + 1),
    ],
)
def test_selected_batch_validates_bounds(
    tmp_path: Path,
    keyword: str,
    value: object,
) -> None:
    with SExpressionWorkspace(tmp_path / f"invalid-{keyword}.db") as workspace:
        queues, state = _batch_state(workspace)
        service = SelectedMergePreflightBatchService(
            queues,
            _FakePreflights(queues.previews),  # type: ignore[arg-type]
        )

        with pytest.raises(ValidationError) as raised:
            service.run(
                "demo",
                "main",
                ["ready"],
                str(state["catalog_id"]),
                **{keyword: value},  # type: ignore[arg-type]
            )

        assert raised.value.code == "INVALID_SELECTED_PREFLIGHT_LIMIT"
