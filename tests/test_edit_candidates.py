from __future__ import annotations

import pytest

from weave_frontend.edit_candidates import EditCandidateService
from weave_frontend.entity_catalog import EntityCatalogService
from weave_frontend.errors import ValidationError
from weave_frontend.sexpr import render_node


def _program(workspace):
    return workspace.create_program(
        "sexpr-demo",
        "main",
        "main.weave",
        program_name="candidate-demo",
    )


def _entry_operations(root_id: str, *, node_id: str | None = None) -> list[dict[str, object]]:
    operation: dict[str, object] = {
        "op": "create_form",
        "parent": root_id,
        "head": "entry",
        "as": "entry",
    }
    if node_id is not None:
        operation["node_id"] = node_id
    return [
        operation,
        {
            "op": "add_atom",
            "parent": "@entry",
            "kind": "symbol",
            "value": "main",
        },
    ]


def test_candidate_edits_do_not_advance_the_branch(sexpr_workspace):
    created = _program(sexpr_workspace)
    branch_head = sexpr_workspace.branch_head("sexpr-demo", "main")
    service = EditCandidateService(sexpr_workspace)
    candidate = service.open("sexpr-demo", "fix-entry")

    applied = service.apply_batch(
        "sexpr-demo",
        candidate["id"],
        "main.weave",
        _entry_operations(created["node_id"]),
        expected_revision_id=candidate["head_revision_id"],
    )

    assert sexpr_workspace.branch_head("sexpr-demo", "main") == branch_head
    assert applied["revision_id"] != branch_head
    inspected = service.inspect("sexpr-demo", candidate["id"])
    assert inspected["head_revision_id"] == applied["revision_id"]
    assert inspected["base_revision_id"] == branch_head
    assert inspected["status"] == "open"
    listed = EntityCatalogService(sexpr_workspace).list_entities(
        "sexpr-demo",
        "main",
        "main.weave",
        revision_id=applied["revision_id"],
    )
    assert any(entity["kind"] == "entry" for entity in listed["entities"])
    assert not any(
        entity["kind"] == "entry"
        for entity in EntityCatalogService(sexpr_workspace).list_entities(
            "sexpr-demo",
            "main",
            "main.weave",
        )["entities"]
    )


def test_stale_candidate_edit_is_rejected(sexpr_workspace):
    created = _program(sexpr_workspace)
    service = EditCandidateService(sexpr_workspace)
    candidate = service.open("sexpr-demo", "stale")
    stale = candidate["head_revision_id"]
    service.apply_batch(
        "sexpr-demo",
        candidate["id"],
        "main.weave",
        _entry_operations(created["node_id"]),
    )
    with pytest.raises(ValidationError) as captured:
        service.apply_batch(
            "sexpr-demo",
            candidate["id"],
            "main.weave",
            _entry_operations(created["node_id"]),
            expected_revision_id=stale,
        )
    assert captured.value.code == "STALE_REVISION"


def test_qualification_binds_the_exact_candidate_head(sexpr_workspace):
    created = _program(sexpr_workspace)
    service = EditCandidateService(sexpr_workspace)
    candidate = service.open("sexpr-demo", "qualify")
    applied = service.apply_batch(
        "sexpr-demo",
        candidate["id"],
        "main.weave",
        _entry_operations(created["node_id"]),
    )
    qualification = service.qualify(
        "sexpr-demo",
        candidate["id"],
        level="syntactic",
        expected_revision_id=applied["revision_id"],
    )
    assert qualification["status"] == "passed"
    assert qualification["revision_id"] == applied["revision_id"]
    assert qualification["evidence"]["syntactic"]["valid"] is True

    service.apply_batch(
        "sexpr-demo",
        candidate["id"],
        "main.weave",
        [
            {
                "op": "create_form",
                "parent": created["node_id"],
                "head": "fn",
                "as": "extra",
            },
            {
                "op": "add_atom",
                "parent": "@extra",
                "kind": "symbol",
                "value": "helper",
            },
        ],
        expected_revision_id=applied["revision_id"],
    )
    viewed = service.inspect("sexpr-demo", candidate["id"])["qualification"]
    assert viewed["stale"] is True
    assert "candidate_content_changed" in viewed["invalidated_by"]


def test_stale_qualification_cannot_publish(sexpr_workspace):
    created = _program(sexpr_workspace)
    service = EditCandidateService(sexpr_workspace)
    candidate = service.open("sexpr-demo", "stale-qual")
    first = service.apply_batch(
        "sexpr-demo",
        candidate["id"],
        "main.weave",
        _entry_operations(created["node_id"]),
    )
    service.qualify(
        "sexpr-demo",
        candidate["id"],
        level="syntactic",
        expected_revision_id=first["revision_id"],
    )
    service.apply_batch(
        "sexpr-demo",
        candidate["id"],
        "main.weave",
        [
            {
                "op": "create_form",
                "parent": created["node_id"],
                "head": "fn",
                "as": "extra",
            },
            {
                "op": "add_atom",
                "parent": "@extra",
                "kind": "symbol",
                "value": "helper",
            },
        ],
        expected_revision_id=first["revision_id"],
    )
    with pytest.raises(ValidationError) as captured:
        service.publish(
            "sexpr-demo",
            candidate["id"],
            "main",
            require_level="syntactic",
        )
    assert captured.value.code == "STALE_QUALIFICATION"


def test_qualified_candidate_publishes_and_mismatched_base_is_rejected(
    sexpr_workspace,
):
    created = _program(sexpr_workspace)
    service = EditCandidateService(sexpr_workspace)
    first = service.open("sexpr-demo", "first")
    applied = service.apply_batch(
        "sexpr-demo",
        first["id"],
        "main.weave",
        _entry_operations(created["node_id"]),
    )
    service.qualify(
        "sexpr-demo",
        first["id"],
        level="syntactic",
        expected_revision_id=applied["revision_id"],
    )
    published = service.publish(
        "sexpr-demo",
        first["id"],
        "main",
        require_level="syntactic",
        expected_revision_id=applied["revision_id"],
    )
    assert published["published"] is True
    assert sexpr_workspace.branch_head("sexpr-demo", "main") == applied["revision_id"]

    second = service.open("sexpr-demo", "second", base_revision_id=first["base_revision_id"])
    service.apply_batch(
        "sexpr-demo",
        second["id"],
        "main.weave",
        _entry_operations(created["node_id"]),
    )
    service.qualify("sexpr-demo", second["id"], level="syntactic")
    with pytest.raises(ValidationError) as captured:
        service.publish("sexpr-demo", second["id"], "main")
    assert captured.value.code == "PUBLICATION_RACE"


def test_abandon_and_revert_preserve_valid_state(sexpr_workspace):
    created = _program(sexpr_workspace)
    branch_head = sexpr_workspace.branch_head("sexpr-demo", "main")
    service = EditCandidateService(sexpr_workspace)
    candidate = service.open("sexpr-demo", "recover")
    first = service.apply_batch(
        "sexpr-demo",
        candidate["id"],
        "main.weave",
        _entry_operations(created["node_id"]),
    )
    reverted = service.revert_last("sexpr-demo", candidate["id"])
    assert reverted["revision_id"] == candidate["head_revision_id"]
    assert reverted["reverted_revision_id"] == first["revision_id"]
    abandoned = service.abandon("sexpr-demo", candidate["id"])
    assert abandoned["status"] == "abandoned"
    assert sexpr_workspace.branch_head("sexpr-demo", "main") == branch_head
    with pytest.raises(ValidationError) as captured:
        service.apply_batch(
            "sexpr-demo",
            candidate["id"],
            "main.weave",
            _entry_operations(created["node_id"]),
        )
    assert captured.value.code == "CANDIDATE_CONFLICT"


def test_recorded_operations_replay_the_same_canonical_source(sexpr_workspace):
    created = _program(sexpr_workspace)
    service = EditCandidateService(sexpr_workspace)
    original = service.open("sexpr-demo", "original")
    pinned_id = "n_replayentry0001"
    applied = service.apply_batch(
        "sexpr-demo",
        original["id"],
        "main.weave",
        _entry_operations(created["node_id"], node_id=pinned_id),
    )
    history = service.inspect("sexpr-demo", original["id"])["edits"]
    replay_ops = [
        {
            "op": "create_form",
            "parent": created["node_id"],
            "head": "entry",
            "node_id": pinned_id,
        },
        {
            "op": "add_atom",
            "parent": pinned_id,
            "kind": "symbol",
            "value": "main",
            "node_id": history[0]["operations"][1]["payload"]["node_id"],
        },
    ]
    replayed = service.replay(
        "sexpr-demo",
        "replayed",
        replay_ops,
        base_revision_id=original["base_revision_id"],
        document="main.weave",
    )
    original_state = sexpr_workspace._state_at_revision(applied["revision_id"])
    replayed_state = sexpr_workspace._state_at_revision(replayed["revision_id"])
    assert render_node(original_state["main.weave"]) == render_node(
        replayed_state["main.weave"]
    )
    assert original_state["main.weave"]["id"] == replayed_state["main.weave"]["id"]
    assert applied["revision_id"] != replayed["revision_id"]
