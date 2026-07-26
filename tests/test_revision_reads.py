from __future__ import annotations

from typing import Any

import pytest

from weave_frontend import NotFoundError
from weave_frontend import mcp_revision_reads
from weave_frontend.revision_reads import RevisionReadService


def _history(sexpr_workspace) -> dict[str, str]:
    created = sexpr_workspace.create_program(
        "sexpr-demo",
        "main",
        "main.weave",
        program_name="revision-reads",
    )
    atom = sexpr_workspace.add_atom(
        "sexpr-demo",
        "main",
        "main.weave",
        created["node_id"],
        "symbol",
        "before",
    )
    historical_revision = str(atom["revision_id"])
    repaired = sexpr_workspace.set_atom(
        "sexpr-demo",
        "main",
        "main.weave",
        atom["node_id"],
        "after",
    )
    return {
        "atom_id": str(atom["node_id"]),
        "historical_revision": historical_revision,
        "current_revision": str(repaired["revision_id"]),
    }


def test_render_defaults_to_head_and_can_pin_history(sexpr_workspace) -> None:
    values = _history(sexpr_workspace)
    service = RevisionReadService(sexpr_workspace)

    current = service.render(
        "sexpr-demo",
        "main",
        "main.weave",
        annotated=False,
    )
    historical = service.render(
        "sexpr-demo",
        "main",
        "main.weave",
        annotated=False,
        revision_id=values["historical_revision"],
    )

    assert current["revision_id"] == values["current_revision"]
    assert current["branch_head_revision_id"] == values["current_revision"]
    assert current["revision_is_branch_head"] is True
    assert "after" in current["source"]
    assert "before" not in current["source"]

    assert historical["revision_id"] == values["historical_revision"]
    assert historical["branch_head_revision_id"] == values["current_revision"]
    assert historical["revision_is_branch_head"] is False
    assert historical["root_node_id"] == current["root_node_id"]
    assert "before" in historical["source"]
    assert "after" not in historical["source"]


def test_find_uses_exact_revision_and_stable_positions(sexpr_workspace) -> None:
    values = _history(sexpr_workspace)
    service = RevisionReadService(sexpr_workspace)

    current = service.find(
        "sexpr-demo",
        "main",
        "main.weave",
        value="after",
    )
    historical = service.find(
        "sexpr-demo",
        "main",
        "main.weave",
        value="before",
        revision_id=values["historical_revision"],
    )
    absent = service.find(
        "sexpr-demo",
        "main",
        "main.weave",
        value="before",
    )

    assert current["revision_is_branch_head"] is True
    assert current["matched_count"] == 1
    assert current["matches"][0]["node_id"] == values["atom_id"]
    assert historical["revision_is_branch_head"] is False
    assert historical["matched_count"] == 1
    assert historical["matches"][0]["node_id"] == values["atom_id"]
    assert historical["matches"][0]["parent_id"] == current["matches"][0]["parent_id"]
    assert historical["matches"][0]["position"] == current["matches"][0]["position"]
    assert absent["matched_count"] == 0
    assert absent["matches"] == []


def test_reads_reject_revision_from_another_project(sexpr_workspace) -> None:
    _history(sexpr_workspace)
    sexpr_workspace.initialize("other-project")
    other = sexpr_workspace.create_program(
        "other-project",
        "main",
        "other.weave",
        program_name="other",
    )
    service = RevisionReadService(sexpr_workspace)

    with pytest.raises(NotFoundError, match="does not belong"):
        service.render(
            "sexpr-demo",
            "main",
            "main.weave",
            revision_id=other["revision_id"],
        )

    with pytest.raises(NotFoundError, match="does not belong"):
        service.find(
            "sexpr-demo",
            "main",
            "main.weave",
            revision_id=other["revision_id"],
        )


def test_reads_report_document_absent_from_historical_revision(sexpr_workspace) -> None:
    initial = sexpr_workspace.branch_head("sexpr-demo", "main")
    sexpr_workspace.create_program(
        "sexpr-demo",
        "main",
        "later.weave",
        program_name="later",
    )
    service = RevisionReadService(sexpr_workspace)

    with pytest.raises(NotFoundError, match="later.weave"):
        service.render(
            "sexpr-demo",
            "main",
            "later.weave",
            revision_id=initial,
        )


class _FakeReads:
    def find(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "project": "demo",
            "branch": "main",
            "document": "main.weave",
            "branch_head_revision_id": "head",
            "revision_id": "historical",
            "revision_is_branch_head": False,
            "matched_count": 0,
            "matches": [],
        }

    def render(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "project": "demo",
            "branch": "main",
            "document": "main.weave",
            "branch_head_revision_id": "head",
            "revision_id": "historical",
            "revision_is_branch_head": False,
            "annotated": False,
            "annotate_atoms": False,
            "root_node_id": "n_root",
            "source": "(program)",
        }


def test_mcp_node_find_preserves_result_list_and_exposes_revision_metadata(
    monkeypatch,
) -> None:
    monkeypatch.setattr(mcp_revision_reads, "revision_reads", lambda: _FakeReads())

    response = mcp_revision_reads.node_find(
        "demo",
        "main",
        "main.weave",
        revision_id="historical",
    )

    assert response["ok"] is True
    assert response["result"] == []
    assert response["matched_count"] == 0
    assert response["revision_id"] == "historical"
    assert response["branch_head_revision_id"] == "head"
    assert response["revision_is_branch_head"] is False


def test_mcp_program_render_preserves_existing_fields_and_adds_revision_metadata(
    monkeypatch,
) -> None:
    monkeypatch.setattr(mcp_revision_reads, "revision_reads", lambda: _FakeReads())

    response = mcp_revision_reads.program_render(
        "demo",
        "main",
        "main.weave",
        annotated=False,
        revision_id="historical",
    )

    assert response["ok"] is True
    assert response["result"]["document"] == "main.weave"
    assert response["result"]["annotated"] is False
    assert response["result"]["source"] == "(program)"
    assert response["result"]["revision_id"] == "historical"
    assert response["result"]["branch_head_revision_id"] == "head"
    assert response["result"]["revision_is_branch_head"] is False
