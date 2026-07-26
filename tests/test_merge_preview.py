from __future__ import annotations

import pytest

from weave_frontend.errors import ConflictError, ValidationError
from weave_frontend.merge_preview import MERGE_PREVIEW_FORMAT, MergePreviewService


def _clean_branches(sexpr_workspace):
    created = sexpr_workspace.create_program(
        "sexpr-demo",
        "main",
        "main.weave",
        program_name="merge-preview",
    )
    root_id = created["node_id"]
    sexpr_workspace.create_branch("sexpr-demo", "target", from_branch="main")
    sexpr_workspace.create_branch("sexpr-demo", "source", from_branch="main")
    target = sexpr_workspace.create_form(
        "sexpr-demo", "target", "main.weave", root_id, "target_only"
    )
    source = sexpr_workspace.create_form(
        "sexpr-demo", "source", "main.weave", root_id, "source_only"
    )
    return {
        "root_id": root_id,
        "target_head": target["revision_id"],
        "source_head": source["revision_id"],
        "source_node_id": source["node_id"],
    }


def test_clean_preview_is_deterministic_and_does_not_advance_target(
    sexpr_workspace,
) -> None:
    values = _clean_branches(sexpr_workspace)
    service = MergePreviewService(sexpr_workspace)

    first = service.preview("sexpr-demo", "target", "source")
    second = service.preview("sexpr-demo", "target", "source")

    assert first == second
    assert first["format"] == MERGE_PREVIEW_FORMAT
    assert first["mergeable"] is True
    assert first["conflicts"] == []
    assert first["target_head_revision_id"] == values["target_head"]
    assert first["source_head_revision_id"] == values["source_head"]
    assert sexpr_workspace.branch_head("sexpr-demo", "target") == values["target_head"]
    assert first["changed_documents"] == ["main.weave"]
    assert first["merged_root_hash"] not in {
        first["target_root_hash"],
        first["source_root_hash"],
    }
    assert first["document_changes"] == [
        {
            "document": "main.weave",
            "status": "modified",
            "before_hash": first["document_changes"][0]["before_hash"],
            "after_hash": first["document_changes"][0]["after_hash"],
            "before_node_count": 7,
            "after_node_count": 9,
            "changed_node_count": 2,
            "change_kind_counts": {
                "added": 2,
                "child_count_changed": 1,
            },
        }
    ]


def test_reviewed_clean_preview_publishes_exact_heads(sexpr_workspace) -> None:
    values = _clean_branches(sexpr_workspace)
    service = MergePreviewService(sexpr_workspace)
    preview = service.preview("sexpr-demo", "target", "source")

    merged = service.merge(
        "sexpr-demo",
        "target",
        "source",
        preview_id=preview["preview_id"],
    )

    assert merged["preview_enforced"] is True
    assert merged["preview_id"] == preview["preview_id"]
    assert merged["reviewed_base_revision_id"] == preview["base_revision_id"]
    assert merged["reviewed_target_head_revision_id"] == values["target_head"]
    assert merged["reviewed_source_head_revision_id"] == values["source_head"]
    assert merged["changed_symbols"] == ["main.weave"]
    assert sexpr_workspace.branch_head("sexpr-demo", "target") == merged["revision_id"]
    source_node = sexpr_workspace.inspect_node(
        "sexpr-demo",
        "target",
        "main.weave",
        values["source_node_id"],
    )
    assert source_node["head"] == "source_only"

    row = sexpr_workspace.db.connection.execute(
        "SELECT parent1_id, parent2_id FROM revisions WHERE id = ?",
        (merged["revision_id"],),
    ).fetchone()
    assert row["parent1_id"] == values["target_head"]
    assert row["parent2_id"] == values["source_head"]


def test_preview_rejects_stale_source_and_target_heads(sexpr_workspace) -> None:
    values = _clean_branches(sexpr_workspace)
    service = MergePreviewService(sexpr_workspace)
    source_preview = service.preview("sexpr-demo", "target", "source")
    target_before = sexpr_workspace.branch_head("sexpr-demo", "target")

    sexpr_workspace.create_form(
        "sexpr-demo", "source", "main.weave", values["root_id"], "source_later"
    )
    with pytest.raises(ValidationError, match="branch heads changed") as source_error:
        service.merge(
            "sexpr-demo",
            "target",
            "source",
            preview_id=source_preview["preview_id"],
        )
    assert source_error.value.code == "STALE_MERGE_PREVIEW"
    assert sexpr_workspace.branch_head("sexpr-demo", "target") == target_before

    target_preview = service.preview("sexpr-demo", "target", "source")
    sexpr_workspace.create_form(
        "sexpr-demo", "target", "main.weave", values["root_id"], "target_later"
    )
    advanced_target = sexpr_workspace.branch_head("sexpr-demo", "target")
    with pytest.raises(ValidationError, match="branch heads changed") as target_error:
        service.merge(
            "sexpr-demo",
            "target",
            "source",
            preview_id=target_preview["preview_id"],
        )
    assert target_error.value.code == "STALE_MERGE_PREVIEW"
    assert sexpr_workspace.branch_head("sexpr-demo", "target") == advanced_target


def test_direct_expected_head_check_rejects_stale_merge(sexpr_workspace) -> None:
    values = _clean_branches(sexpr_workspace)
    sexpr_workspace.create_form(
        "sexpr-demo", "source", "main.weave", values["root_id"], "source_later"
    )

    with pytest.raises(ValidationError) as captured:
        sexpr_workspace.merge(
            "sexpr-demo",
            target_branch="target",
            source_branch="source",
            expected_target_head=values["target_head"],
            expected_source_head=values["source_head"],
        )
    assert captured.value.code == "STALE_MERGE_PREVIEW"
    assert sexpr_workspace.branch_head("sexpr-demo", "target") == values["target_head"]


def test_conflict_preview_is_non_mutating_and_publish_returns_conflict(
    sexpr_workspace,
) -> None:
    created = sexpr_workspace.create_program(
        "sexpr-demo", "main", "main.weave", program_name="conflict"
    )
    atom = sexpr_workspace.add_atom(
        "sexpr-demo",
        "main",
        "main.weave",
        created["node_id"],
        "string",
        "base",
    )
    sexpr_workspace.create_branch("sexpr-demo", "target", from_branch="main")
    sexpr_workspace.create_branch("sexpr-demo", "source", from_branch="main")
    target = sexpr_workspace.set_atom(
        "sexpr-demo", "target", "main.weave", atom["node_id"], "target"
    )
    sexpr_workspace.set_atom(
        "sexpr-demo", "source", "main.weave", atom["node_id"], "source"
    )
    service = MergePreviewService(sexpr_workspace)

    preview = service.preview("sexpr-demo", "target", "source")

    assert preview["mergeable"] is False
    assert preview["merged_root_hash"] is None
    assert preview["changed_documents"] == []
    assert preview["document_changes"] == []
    assert preview["conflicts"]
    assert atom["node_id"] in preview["conflicts"][0]
    assert sexpr_workspace.branch_head("sexpr-demo", "target") == target["revision_id"]

    with pytest.raises(ConflictError) as captured:
        service.merge(
            "sexpr-demo",
            "target",
            "source",
            preview_id=preview["preview_id"],
        )
    assert captured.value.conflicts == preview["conflicts"]
    assert sexpr_workspace.branch_head("sexpr-demo", "target") == target["revision_id"]


def test_merge_without_preview_remains_supported(sexpr_workspace) -> None:
    _clean_branches(sexpr_workspace)
    service = MergePreviewService(sexpr_workspace)

    merged = service.merge("sexpr-demo", "target", "source")

    assert merged["preview_enforced"] is False
    assert merged["preview_id"] is None
    assert merged["reviewed_base_revision_id"] is None
    assert merged["changed_symbols"] == ["main.weave"]


def test_preview_id_is_bound_to_project_and_branch_direction(sexpr_workspace) -> None:
    _clean_branches(sexpr_workspace)
    service = MergePreviewService(sexpr_workspace)

    forward = service.preview("sexpr-demo", "target", "source")
    reverse = service.preview("sexpr-demo", "source", "target")

    assert forward["preview_id"] != reverse["preview_id"]
    with pytest.raises(ValidationError) as captured:
        service.merge(
            "sexpr-demo",
            "source",
            "target",
            preview_id=forward["preview_id"],
        )
    assert captured.value.code == "STALE_MERGE_PREVIEW"
