from __future__ import annotations

import json
from pathlib import Path

import pytest

from weave_frontend import SExpressionWorkspace, ValidationError
from weave_frontend.batch_edit import EditBatchExecutor
from weave_frontend.metadata_build_targets import BuildTargetRegistry
from weave_frontend.project_metadata import TASK_CONTRACT_PREFIX
from weave_frontend.task_contracts import TaskContractRegistry
from weave_frontend.task_scoped_batch import TaskScopedBatchExecutor


def _workspace(path: Path) -> tuple[SExpressionWorkspace, dict[str, object]]:
    workspace = SExpressionWorkspace(path)
    workspace.initialize("demo")
    main = workspace.create_program(
        "demo",
        "main",
        "main.weave",
        program_name="tasks",
    )
    workspace.create_program(
        "demo",
        "main",
        "other.weave",
        program_name="other",
        expected_revision_id=str(main["revision_id"]),
    )
    return workspace, main


def test_task_contracts_are_revisioned_bounded_and_non_source(tmp_path: Path) -> None:
    workspace, _ = _workspace(tmp_path / "tasks.db")
    registry = TaskContractRegistry(workspace)
    targets = BuildTargetRegistry(workspace)
    with workspace:
        base = workspace.branch_head("demo", "main")
        created = registry.create(
            "demo",
            "main",
            "implement-loop",
            owner="agent-a",
            objective="Implement the loop body without changing unrelated modules.",
            allowed_documents=["main.weave"],
            acceptance_criteria=["program validates", "smoke test passes"],
            expected_revision_id=base,
        )

        assert created["base_revision_id"] == base
        assert created["branch"] == "main"
        assert created["selected_branch"] == "main"
        assert created["storage_document"] == f"{TASK_CONTRACT_PREFIX}implement-loop"
        assert created["allowed_documents"] == ["main.weave"]
        assert len(created["contract_hash"]) == 64
        assert targets.program_documents("demo") == ["main.weave", "other.weave"]

        historical = registry.get(
            "demo",
            "implement-loop",
            revision_id=created["revision_id"],
        )
        assert historical["contract_hash"] == created["contract_hash"]
        assert historical["task_revision_id"] == created["revision_id"]

        page = registry.list_page("demo", limit=10)
        assert page["returned_task_count"] == 1
        assert page["tasks"][0]["name"] == "implement-loop"
        assert page["tasks"][0]["allowed_document_count"] == 1
        assert len(page["page_id"]) == 64

        with pytest.raises(ValidationError) as raised:
            registry.create(
                "demo",
                "main",
                "bad-scope",
                owner="agent-a",
                objective="Invalid reserved scope.",
                allowed_documents=[f"{TASK_CONTRACT_PREFIX}implement-loop"],
            )
        assert raised.value.code == "INVALID_TASK_DOCUMENT_REFERENCE"


def test_task_status_transitions_require_owner_and_preserve_identity(tmp_path: Path) -> None:
    workspace, _ = _workspace(tmp_path / "task-status.db")
    registry = TaskContractRegistry(workspace)
    with workspace:
        created = registry.create(
            "demo",
            "main",
            "status-task",
            owner="agent-a",
            objective="Track one task lifecycle.",
            allowed_documents=["main.weave"],
        )
        with pytest.raises(ValidationError) as raised:
            registry.set_status(
                "demo",
                "main",
                "status-task",
                "in_progress",
                actor="agent-b",
                expected_revision_id=created["revision_id"],
            )
        assert raised.value.code == "TASK_OWNER_MISMATCH"

        started = registry.set_status(
            "demo",
            "main",
            "status-task",
            "in_progress",
            actor="agent-a",
            expected_revision_id=created["revision_id"],
        )
        assert started["root_node_id"] == created["root_node_id"]
        assert started["status"] == "in_progress"
        assert started["contract_hash"] != created["contract_hash"]

        completed = registry.set_status(
            "demo",
            "main",
            "status-task",
            "complete",
            actor="agent-a",
            expected_revision_id=started["revision_id"],
        )
        with pytest.raises(ValidationError) as raised:
            registry.set_status(
                "demo",
                "main",
                "status-task",
                "in_progress",
                actor="agent-a",
                expected_revision_id=completed["revision_id"],
            )
        assert raised.value.code == "INVALID_TASK_STATUS_TRANSITION"


def test_task_scoped_batch_enforces_dependencies_scope_and_audit(tmp_path: Path) -> None:
    workspace, main = _workspace(tmp_path / "task-batch.db")
    registry = TaskContractRegistry(workspace)
    executor = TaskScopedBatchExecutor(registry, EditBatchExecutor(workspace))
    with workspace:
        dependency = registry.create(
            "demo",
            "main",
            "dependency",
            owner="agent-a",
            objective="Complete prerequisite work.",
            allowed_documents=["main.weave"],
        )
        task = registry.create(
            "demo",
            "main",
            "implementation",
            owner="agent-a",
            objective="Perform the scoped edit.",
            allowed_documents=["main.weave"],
            dependencies=["dependency"],
            expected_revision_id=dependency["revision_id"],
        )
        operation = {
            "op": "create_form",
            "parent": main["root_node_id"],
            "head": "do",
            "as": "body",
        }

        with pytest.raises(ValidationError) as raised:
            executor.apply(
                "demo",
                "implementation",
                "main.weave",
                [operation],
                actor="agent-a",
                expected_revision_id=task["revision_id"],
            )
        assert raised.value.code == "TASK_DEPENDENCIES_INCOMPLETE"

        dependency_complete = registry.set_status(
            "demo",
            "main",
            "dependency",
            "complete",
            actor="agent-a",
            expected_revision_id=task["revision_id"],
        )
        with pytest.raises(ValidationError) as raised:
            executor.apply(
                "demo",
                "implementation",
                "other.weave",
                [operation],
                actor="agent-a",
                expected_revision_id=dependency_complete["revision_id"],
            )
        assert raised.value.code == "TASK_SCOPE_VIOLATION"

        with pytest.raises(ValidationError) as raised:
            executor.apply(
                "demo",
                "implementation",
                "main.weave",
                [operation],
                actor="agent-b",
                expected_revision_id=dependency_complete["revision_id"],
            )
        assert raised.value.code == "TASK_OWNER_MISMATCH"

        result = executor.apply(
            "demo",
            "implementation",
            "main.weave",
            [operation],
            actor="agent-a",
            expected_revision_id=dependency_complete["revision_id"],
            include_operation_results=True,
        )
        assert result["task"] == "implementation"
        assert result["task_scope_enforced"] is True
        assert result["task_owner"] == "agent-a"
        assert result["operation_count"] == 1

        row = workspace.db.connection.execute(
            """SELECT payload_json FROM operations
               WHERE revision_id = ? AND operation_kind = 'create_form'""",
            (result["revision_id"],),
        ).fetchone()
        payload = json.loads(str(row["payload_json"]))
        audit = payload["task_contract"]
        assert audit["format"] == "weave-task-audit-v1"
        assert audit["task"] == "implementation"
        assert audit["actor"] == "agent-a"
        assert audit["contract_hash"] == result["task_contract_hash"]
