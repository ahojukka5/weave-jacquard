from __future__ import annotations

import json
from pathlib import Path

import pytest

from weave_frontend import ConflictError, SExpressionWorkspace, ValidationError
from weave_frontend.merge_preview import MergePreviewService
from weave_frontend.metadata_build_targets import BuildTargetRegistry
from weave_frontend.revert import RevertService
from weave_frontend.sexpr import head_symbol, walk_nodes
from weave_frontend.test_targets import TestTargetRegistry


def _workspace(path: Path) -> tuple[SExpressionWorkspace, str, str]:
    workspace = SExpressionWorkspace(path)
    _, initial_revision = workspace.initialize("demo")
    program = workspace.create_program(
        "demo",
        "main",
        "main.weave",
        program_name="revert-demo",
        expected_revision_id=initial_revision,
    )
    documents = workspace.list_documents("demo", "main")
    root_id = str(documents[0]["root_node_id"])
    return workspace, str(program["revision_id"]), root_id


def _service(workspace: SExpressionWorkspace) -> RevertService:
    return RevertService(workspace, MergePreviewService(workspace))


def test_revert_preserves_independent_later_edits_and_writes_new_history(
    tmp_path: Path,
) -> None:
    workspace, program_revision, root_id = _workspace(tmp_path / "revert.db")
    service = _service(workspace)
    with workspace:
        selected = workspace.create_form(
            "demo",
            "main",
            "main.weave",
            root_id,
            "do",
            expected_revision_id=program_revision,
        )
        later = workspace.create_program(
            "demo",
            "main",
            "other.weave",
            program_name="independent",
            expected_revision_id=selected["revision_id"],
        )
        current_head = str(later["revision_id"])

        preview = service.preview("demo", "main", str(selected["revision_id"]))
        assert preview["revertible"] is True
        assert preview["would_change_branch"] is True
        assert preview["branch_head_revision_id"] == current_head
        assert preview["reverted_parent_revision_id"] == program_revision
        assert preview["changed_documents"] == ["main.weave"]
        assert [item["document"] for item in preview["document_changes"]] == [
            "main.weave"
        ]
        assert workspace.branch_head("demo", "main") == current_head

        result = service.revert(
            "demo",
            "main",
            str(selected["revision_id"]),
            preview_id=preview["preview_id"],
            author="recovery-agent",
        )
        assert result["parent_revision_id"] == current_head
        assert result["history_rewritten"] is False
        assert workspace.branch_head("demo", "main") == result["revision_id"]
        document_names = {
            item["document"] for item in workspace.list_documents("demo", "main")
        }
        assert document_names == {"main.weave", "other.weave"}
        state = workspace._state_at_revision(result["revision_id"])
        assert set(state) == {"main.weave", "other.weave"}
        assert "do" not in {
            head_symbol(node) for node in walk_nodes(state["main.weave"])
        }
        assert any(
            node.get("kind") == "string" and node.get("value") == "independent"
            for node in walk_nodes(state["other.weave"])
        )

        revision_row = workspace.db.connection.execute(
            "SELECT parent1_id, parent2_id FROM revisions WHERE id = ?",
            (result["revision_id"],),
        ).fetchone()
        assert revision_row["parent1_id"] == current_head
        assert revision_row["parent2_id"] is None
        operation = workspace.db.connection.execute(
            """SELECT operation_kind, target, payload_json FROM operations
               WHERE revision_id = ?""",
            (result["revision_id"],),
        ).fetchone()
        assert operation["operation_kind"] == "revert"
        assert operation["target"] == "main"
        payload = json.loads(str(operation["payload_json"]))
        assert payload["preview_id"] == preview["preview_id"]
        assert payload["reverted_revision_id"] == selected["revision_id"]
        assert payload["reviewed_branch_head_revision_id"] == current_head
        assert payload["prospective_root_hash"] == result["root_hash"]


def test_revert_reports_conflict_when_later_edit_overlaps_selected_change(
    tmp_path: Path,
) -> None:
    workspace, program_revision, _ = _workspace(tmp_path / "conflict.db")
    service = _service(workspace)
    with workspace:
        state = workspace._state_at_revision(program_revision)
        name_atom = next(
            node
            for node in walk_nodes(state["main.weave"])
            if node.get("kind") == "string" and node.get("value") == "revert-demo"
        )
        selected = workspace.set_atom(
            "demo",
            "main",
            "main.weave",
            str(name_atom["id"]),
            "selected-change",
            expected_revision_id=program_revision,
        )
        later = workspace.set_atom(
            "demo",
            "main",
            "main.weave",
            str(name_atom["id"]),
            "later-change",
            expected_revision_id=selected["revision_id"],
        )

        preview = service.preview("demo", "main", str(selected["revision_id"]))
        assert preview["revertible"] is False
        assert preview["would_change_branch"] is False
        assert preview["conflicts"]
        assert preview["prospective_root_hash"] is None
        assert workspace.branch_head("demo", "main") == later["revision_id"]
        with pytest.raises(ConflictError):
            service.revert(
                "demo",
                "main",
                str(selected["revision_id"]),
                preview_id=preview["preview_id"],
            )
        assert workspace.branch_head("demo", "main") == later["revision_id"]


def test_revert_rejects_stale_preview_unreachable_revision_and_noop(tmp_path: Path) -> None:
    workspace, program_revision, root_id = _workspace(tmp_path / "guards.db")
    service = _service(workspace)
    with workspace:
        selected = workspace.create_form(
            "demo",
            "main",
            "main.weave",
            root_id,
            "do",
            expected_revision_id=program_revision,
        )
        preview = service.preview("demo", "main", str(selected["revision_id"]))
        advanced = workspace.create_form(
            "demo",
            "main",
            "main.weave",
            root_id,
            "block",
            expected_revision_id=selected["revision_id"],
        )
        with pytest.raises(ValidationError) as raised:
            service.revert(
                "demo",
                "main",
                str(selected["revision_id"]),
                preview_id=preview["preview_id"],
            )
        assert raised.value.code == "STALE_REVERT_PREVIEW"
        assert workspace.branch_head("demo", "main") == advanced["revision_id"]

        fresh = service.preview("demo", "main", str(selected["revision_id"]))
        reverted = service.revert(
            "demo",
            "main",
            str(selected["revision_id"]),
            preview_id=fresh["preview_id"],
        )
        noop = service.preview("demo", "main", str(selected["revision_id"]))
        assert noop["revertible"] is True
        assert noop["would_change_branch"] is False
        with pytest.raises(ValidationError) as raised:
            service.revert(
                "demo",
                "main",
                str(selected["revision_id"]),
                preview_id=noop["preview_id"],
            )
        assert raised.value.code == "REVERT_NO_CHANGES"
        assert workspace.branch_head("demo", "main") == reverted["revision_id"]

        workspace.create_branch_at_revision(
            "demo",
            "feature",
            program_revision,
        )
        feature = workspace.create_form(
            "demo",
            "feature",
            "main.weave",
            root_id,
            "feature-only",
            expected_revision_id=program_revision,
        )
        with pytest.raises(ValidationError) as raised:
            service.preview("demo", "main", str(feature["revision_id"]))
        assert raised.value.code == "REVISION_NOT_ON_BRANCH"

        initial = workspace.list_history("demo", "main", limit=100)[-1]["id"]
        with pytest.raises(ValidationError) as raised:
            service.preview("demo", "main", str(initial))
        assert raised.value.code == "INITIAL_REVISION_NOT_REVERTIBLE"


def test_revert_rejects_dangling_build_and_test_metadata(tmp_path: Path) -> None:
    workspace, program_revision, _ = _workspace(tmp_path / "metadata.db")
    service = _service(workspace)
    targets = BuildTargetRegistry(workspace)
    tests = TestTargetRegistry(workspace)
    with workspace:
        target = targets.set(
            "demo",
            "main",
            "application",
            "main.weave",
            expected_revision_id=program_revision,
        )
        test = tests.set(
            "demo",
            "main",
            "smoke",
            "application",
            expected_revision_id=target["revision_id"],
        )

        with pytest.raises(ValidationError) as raised:
            service.preview("demo", "main", str(target["revision_id"]))
        assert raised.value.code == "INVALID_TEST_TARGET_REFERENCE"
        assert workspace.branch_head("demo", "main") == test["revision_id"]

        with pytest.raises(ValidationError) as raised:
            service.preview("demo", "main", program_revision)
        assert raised.value.code == "INVALID_BUILD_TARGET_DOCUMENT_REFERENCE"
        assert workspace.branch_head("demo", "main") == test["revision_id"]
