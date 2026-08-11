from __future__ import annotations

import pytest

from weave_frontend.builds import BuildTargetRegistry
from weave_frontend.errors import ConflictError, ValidationError
from weave_frontend.merges import (
    MERGE_TARGET_IMPACT_FORMAT,
    MergePreviewService,
    MergeTargetImpactService,
)


def _service(sexpr_workspace) -> MergeTargetImpactService:
    return MergeTargetImpactService(
        MergePreviewService(sexpr_workspace),
        BuildTargetRegistry(sexpr_workspace),
    )


def _program_with_atom(sexpr_workspace, document: str, value: str) -> dict[str, str]:
    created = sexpr_workspace.create_program(
        "sexpr-demo", "main", document, program_name=document
    )
    atom = sexpr_workspace.add_atom(
        "sexpr-demo", "main", document, created["node_id"], "string", value
    )
    return {"root_id": created["node_id"], "atom_id": atom["node_id"]}


def _coverage_project(sexpr_workspace):
    docs = {
        name: _program_with_atom(sexpr_workspace, name, name)
        for name in ("main.weave", "lib.weave", "spare.weave", "orphan.weave")
    }
    targets = BuildTargetRegistry(sexpr_workspace)
    targets.set(
        "sexpr-demo",
        "main",
        "application",
        "main.weave",
        additional_documents=["lib.weave"],
    )
    targets.set("sexpr-demo", "main", "main-only", "main.weave")
    targets.set("sexpr-demo", "main", "spare", "spare.weave")
    sexpr_workspace.create_branch("sexpr-demo", "target", from_branch="main")
    sexpr_workspace.create_branch("sexpr-demo", "source", from_branch="main")
    return docs


def test_impact_maps_source_merge_changes_and_uncovered_documents(
    sexpr_workspace,
) -> None:
    docs = _coverage_project(sexpr_workspace)
    target_head = sexpr_workspace.set_atom(
        "sexpr-demo",
        "target",
        "spare.weave",
        docs["spare.weave"]["atom_id"],
        "target-spare",
    )["revision_id"]
    sexpr_workspace.set_atom(
        "sexpr-demo",
        "source",
        "main.weave",
        docs["main.weave"]["atom_id"],
        "source-main",
    )
    sexpr_workspace.set_atom(
        "sexpr-demo",
        "source",
        "lib.weave",
        docs["lib.weave"]["atom_id"],
        "source-lib",
    )
    source_head = sexpr_workspace.set_atom(
        "sexpr-demo",
        "source",
        "orphan.weave",
        docs["orphan.weave"]["atom_id"],
        "source-orphan",
    )["revision_id"]

    result = _service(sexpr_workspace).page(
        "sexpr-demo", "target", "source", limit=10
    )

    assert result["format"] == MERGE_TARGET_IMPACT_FORMAT
    assert result["target_head_revision_id"] == target_head
    assert result["source_head_revision_id"] == source_head
    assert result["changed_program_documents"] == [
        "lib.weave",
        "main.weave",
        "orphan.weave",
    ]
    assert "spare.weave" not in result["changed_program_documents"]
    assert result["candidate_covered_changed_documents"] == [
        "lib.weave",
        "main.weave",
    ]
    assert result["uncovered_changed_documents"] == ["orphan.weave"]
    assert result["total_affected_target_count"] == 2
    assert result["unaffected_target_count"] == 1
    assert [item["name"] for item in result["affected_targets"]] == [
        "application",
        "main-only",
    ]
    application = result["affected_targets"][0]
    assert application["status"] == "unchanged"
    assert application["affected_reasons"] == ["source_document_changed"]
    assert application["changed_source_documents"] == ["lib.weave", "main.weave"]
    assert result["affected_targets"][1]["changed_source_documents"] == ["main.weave"]
    assert sexpr_workspace.branch_head("sexpr-demo", "target") == target_head
    assert sexpr_workspace.branch_head("sexpr-demo", "source") == source_head


def test_impact_reports_added_removed_and_modified_targets(sexpr_workspace) -> None:
    _program_with_atom(sexpr_workspace, "main.weave", "main")
    _program_with_atom(sexpr_workspace, "lib.weave", "lib")
    targets = BuildTargetRegistry(sexpr_workspace)
    targets.set("sexpr-demo", "main", "removed", "main.weave")
    targets.set("sexpr-demo", "main", "modified", "main.weave")
    sexpr_workspace.create_branch("sexpr-demo", "target", from_branch="main")
    sexpr_workspace.create_branch("sexpr-demo", "source", from_branch="main")
    targets.delete("sexpr-demo", "source", "removed")
    targets.set(
        "sexpr-demo",
        "source",
        "modified",
        "main.weave",
        additional_documents=["lib.weave"],
    )
    targets.set("sexpr-demo", "source", "added", "lib.weave")

    result = _service(sexpr_workspace).page(
        "sexpr-demo", "target", "source", limit=10
    )
    by_name = {item["name"]: item for item in result["affected_targets"]}

    assert list(by_name) == ["added", "modified", "removed"]
    assert by_name["added"]["status"] == "added"
    assert by_name["added"]["affected_reasons"] == ["target_added"]
    assert by_name["added"]["before"] is None
    assert by_name["removed"]["status"] == "removed"
    assert by_name["removed"]["affected_reasons"] == ["target_removed"]
    assert by_name["removed"]["after"] is None
    assert by_name["modified"]["status"] == "modified"
    assert by_name["modified"]["affected_reasons"] == [
        "target_definition_changed"
    ]
    assert by_name["modified"]["after"]["additional_documents"] == ["lib.weave"]
    assert result["changed_target_documents"] == [
        "@build-target/added",
        "@build-target/modified",
        "@build-target/removed",
    ]
    assert result["unaffected_target_count"] == 0


def test_impact_paginates_deterministically(sexpr_workspace) -> None:
    doc = _program_with_atom(sexpr_workspace, "main.weave", "main")
    targets = BuildTargetRegistry(sexpr_workspace)
    for name in ("alpha", "beta", "gamma", "omega", "zeta"):
        targets.set("sexpr-demo", "main", name, "main.weave")
    sexpr_workspace.create_branch("sexpr-demo", "target", from_branch="main")
    sexpr_workspace.create_branch("sexpr-demo", "source", from_branch="main")
    sexpr_workspace.set_atom(
        "sexpr-demo", "source", "main.weave", doc["atom_id"], "changed"
    )
    service = _service(sexpr_workspace)

    first = service.page("sexpr-demo", "target", "source", limit=2)
    second = service.page(
        "sexpr-demo",
        "target",
        "source",
        start_index=first["next_index"],
        limit=2,
    )
    third = service.page(
        "sexpr-demo",
        "target",
        "source",
        start_index=second["next_index"],
        limit=2,
    )

    assert [item["name"] for item in first["affected_targets"]] == ["alpha", "beta"]
    assert [item["name"] for item in second["affected_targets"]] == ["gamma", "omega"]
    assert [item["name"] for item in third["affected_targets"]] == ["zeta"]
    assert [first["returned_count"], second["returned_count"], third["returned_count"]] == [2, 2, 1]
    assert first["has_more"] is True
    assert second["has_more"] is True
    assert third["has_more"] is False


def test_impact_rejects_stale_preview(sexpr_workspace) -> None:
    doc = _program_with_atom(sexpr_workspace, "main.weave", "main")
    BuildTargetRegistry(sexpr_workspace).set(
        "sexpr-demo", "main", "application", "main.weave"
    )
    sexpr_workspace.create_branch("sexpr-demo", "target", from_branch="main")
    sexpr_workspace.create_branch("sexpr-demo", "source", from_branch="main")
    preview = MergePreviewService(sexpr_workspace).preview(
        "sexpr-demo", "target", "source"
    )
    sexpr_workspace.set_atom(
        "sexpr-demo", "source", "main.weave", doc["atom_id"], "advanced"
    )

    with pytest.raises(ValidationError) as raised:
        _service(sexpr_workspace).page(
            "sexpr-demo",
            "target",
            "source",
            preview_id=preview["preview_id"],
        )
    assert raised.value.code == "STALE_MERGE_PREVIEW"


def test_impact_rejects_conflict_without_mutation(sexpr_workspace) -> None:
    doc = _program_with_atom(sexpr_workspace, "main.weave", "base")
    BuildTargetRegistry(sexpr_workspace).set(
        "sexpr-demo", "main", "application", "main.weave"
    )
    sexpr_workspace.create_branch("sexpr-demo", "target", from_branch="main")
    sexpr_workspace.create_branch("sexpr-demo", "source", from_branch="main")
    target_head = sexpr_workspace.set_atom(
        "sexpr-demo", "target", "main.weave", doc["atom_id"], "target"
    )["revision_id"]
    source_head = sexpr_workspace.set_atom(
        "sexpr-demo", "source", "main.weave", doc["atom_id"], "source"
    )["revision_id"]

    with pytest.raises(ConflictError):
        _service(sexpr_workspace).page("sexpr-demo", "target", "source")
    assert sexpr_workspace.branch_head("sexpr-demo", "target") == target_head
    assert sexpr_workspace.branch_head("sexpr-demo", "source") == source_head


@pytest.mark.parametrize(
    ("start_index", "limit", "code"),
    [
        (-1, 50, "INVALID_MERGE_TARGET_IMPACT_INDEX"),
        (True, 50, "INVALID_MERGE_TARGET_IMPACT_INDEX"),
        (0, 0, "INVALID_MERGE_TARGET_IMPACT_LIMIT"),
        (0, 201, "INVALID_MERGE_TARGET_IMPACT_LIMIT"),
    ],
)
def test_impact_validates_page_bounds(
    sexpr_workspace,
    start_index,
    limit,
    code,
) -> None:
    _program_with_atom(sexpr_workspace, "main.weave", "main")
    sexpr_workspace.create_branch("sexpr-demo", "target", from_branch="main")
    sexpr_workspace.create_branch("sexpr-demo", "source", from_branch="main")

    with pytest.raises(ValidationError) as raised:
        _service(sexpr_workspace).page(
            "sexpr-demo",
            "target",
            "source",
            start_index=start_index,
            limit=limit,
        )
    assert raised.value.code == code
