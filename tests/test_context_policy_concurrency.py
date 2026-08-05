from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from weave_frontend import SExpressionWorkspace, ValidationError
from weave_frontend.concurrent_merge_policy import MergePolicyRegistry


def _table_count(workspace: SExpressionWorkspace, table: str) -> int:
    row = workspace.db.connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
    return int(row["count"])


def _operation(workspace: SExpressionWorkspace, revision_id: str) -> dict[str, Any]:
    row = workspace.db.connection.execute(
        """SELECT operation_kind, target, payload_json
           FROM operations WHERE revision_id = ?""",
        (revision_id,),
    ).fetchone()
    assert row is not None
    import json

    return {
        "operation_kind": row["operation_kind"],
        "target": row["target"],
        "payload": json.loads(str(row["payload_json"])),
    }


def test_context_document_and_revision_publish_atomically(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "context.db") as workspace:
        _, initial_revision = workspace.initialize("demo")

        result = workspace.add_context(
            "demo",
            "main",
            scope_kind="document",
            scope_name="main.weave",
            title="Invariant",
            body="The entry point returns i32.",
            expected_revision_id=initial_revision,
        )

        assert result["base_revision_id"] == initial_revision
        assert workspace.branch_head("demo", "main") == result["revision_id"]
        assert _table_count(workspace, "documents") == 1
        assert _table_count(workspace, "revision_documents") == 1
        operation = _operation(workspace, result["revision_id"])
        assert operation == {
            "operation_kind": "add_context",
            "target": "main.weave",
            "payload": {"document_id": result["document_id"]},
        }
        assert (
            workspace.get_context("demo", "main", scope_name="main.weave")[0]["body"]
            == "The entry point returns i32."
        )


def test_identical_context_reuses_content_addressed_document(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "context-reuse.db") as workspace:
        workspace.initialize("demo")
        first = workspace.add_context(
            "demo",
            "main",
            scope_kind="document",
            scope_name="main.weave",
            title="Invariant",
            body="Stable content.",
        )
        second = workspace.add_context(
            "demo",
            "main",
            scope_kind="document",
            scope_name="main.weave",
            title="Invariant",
            body="Stable content.",
            expected_revision_id=first["revision_id"],
        )

        assert second["document_id"] == first["document_id"]
        assert _table_count(workspace, "documents") == 1
        assert _table_count(workspace, "revision_documents") == 2
        assert len(workspace.get_context("demo", "main", scope_name="main.weave")) == 1


def test_stale_context_rejects_without_orphan_document(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "stale-context.db") as workspace:
        _, initial_revision = workspace.initialize("demo")
        accepted = workspace.create_program(
            "demo",
            "main",
            "main.weave",
            program_name="accepted",
            expected_revision_id=initial_revision,
        )
        counts = {
            table: _table_count(workspace, table)
            for table in ("documents", "revision_documents", "revisions", "operations")
        }

        with pytest.raises(ValidationError) as raised:
            workspace.add_context(
                "demo",
                "main",
                scope_kind="document",
                scope_name="main.weave",
                title="Stale",
                body="Must not survive.",
                expected_revision_id=initial_revision,
            )

        assert raised.value.code == "STALE_BRANCH_HEAD"
        assert workspace.branch_head("demo", "main") == accepted["revision_id"]
        assert {table: _table_count(workspace, table) for table in counts} == counts


def test_transaction_prepare_failure_rolls_back_document_and_revision(
    tmp_path: Path,
) -> None:
    with SExpressionWorkspace(tmp_path / "prepare-rollback.db") as workspace:
        _, initial_revision = workspace.initialize("demo")
        state = workspace._state_at_revision(initial_revision)
        counts = {
            table: _table_count(workspace, table)
            for table in ("documents", "revision_documents", "revisions", "operations")
        }

        def fail_after_insert(connection):
            connection.execute(
                """INSERT INTO documents(
                       id, scope_kind, scope_name, title, body, content_hash
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    "document-doomed",
                    "project",
                    "demo",
                    "Doomed",
                    "rollback",
                    "0" * 64,
                ),
            )
            raise RuntimeError("stop publication")

        with pytest.raises(RuntimeError, match="stop publication"):
            workspace._commit(
                "demo",
                "main",
                state,
                message="doomed",
                author="test",
                operations=(),
                expected_branch_heads={"main": initial_revision},
                prepare_transaction=fail_after_insert,
            )

        assert workspace.branch_head("demo", "main") == initial_revision
        assert {table: _table_count(workspace, table) for table in counts} == counts


def test_merge_policy_document_and_revision_publish_atomically(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "policy.db") as workspace:
        _, initial_revision = workspace.initialize("demo")
        policies = MergePolicyRegistry(workspace)

        result = policies.set(
            "demo",
            "main",
            require_preflight=True,
            require_affected_validation=True,
            allow_uncovered_documents=False,
            max_affected_targets=7,
            expected_revision_id=initial_revision,
        )

        assert result["base_revision_id"] == initial_revision
        assert result["policy_revision_id"] == result["revision_id"]
        assert workspace.branch_head("demo", "main") == result["revision_id"]
        operation = _operation(workspace, result["revision_id"])
        assert operation["operation_kind"] == "set_merge_policy"
        assert operation["target"] == "demo"
        assert operation["payload"]["document_id"] == result["document_id"]
        assert operation["payload"]["policy_hash"] == result["policy_hash"]
        resolved = policies.get("demo", "main")
        assert resolved["policy_hash"] == result["policy_hash"]
        assert resolved["max_affected_targets"] == 7


def test_stale_merge_policy_rejects_without_orphan_document(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "stale-policy.db") as workspace:
        _, initial_revision = workspace.initialize("demo")
        accepted = workspace.create_program(
            "demo",
            "main",
            "main.weave",
            program_name="accepted",
            expected_revision_id=initial_revision,
        )
        policies = MergePolicyRegistry(workspace)
        counts = {
            table: _table_count(workspace, table)
            for table in ("documents", "revision_documents", "revisions", "operations")
        }

        with pytest.raises(ValidationError) as raised:
            policies.set(
                "demo",
                "main",
                require_preflight=True,
                require_affected_validation=True,
                allow_uncovered_documents=False,
                max_affected_targets=3,
                expected_revision_id=initial_revision,
            )

        assert raised.value.code == "STALE_BRANCH_HEAD"
        assert workspace.branch_head("demo", "main") == accepted["revision_id"]
        assert {table: _table_count(workspace, table) for table in counts} == counts
