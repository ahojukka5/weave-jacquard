from __future__ import annotations

import pytest

from weave_frontend.batch_edit import EditBatchExecutor
from weave_frontend.entity_catalog import EntityCatalogService
from weave_frontend.errors import ValidationError


def _program(workspace):
    return workspace.create_program(
        "sexpr-demo",
        "main",
        "main.weave",
        program_name="identity-demo",
    )


def _add_function(workspace, root_id, name, alias):
    return EditBatchExecutor(workspace).apply(
        "sexpr-demo",
        "main",
        "main.weave",
        [
            {
                "op": "create_form",
                "parent": root_id,
                "head": "fn",
                "as": alias,
            },
            {
                "op": "add_atom",
                "parent": f"@{alias}",
                "kind": "symbol",
                "value": name,
            },
        ],
    )


def test_identity_survives_unrelated_atom_edits(sexpr_workspace):
    created = _program(sexpr_workspace)
    added = _add_function(sexpr_workspace, created["node_id"], "alpha", "fn")
    function_id = added["aliases"]["fn"]
    catalog = EntityCatalogService(sexpr_workspace)
    before = catalog.inspect_identity(
        "sexpr-demo",
        "main",
        "main.weave",
        function_id,
    )

    name_atom = EntityCatalogService(sexpr_workspace).inspect_entity(
        "sexpr-demo",
        "main",
        "main.weave",
        node_id=function_id,
    )["children"][1]["node_id"]
    sexpr_workspace.set_atom(
        "sexpr-demo",
        "main",
        "main.weave",
        name_atom,
        "beta",
    )
    after = catalog.inspect_identity(
        "sexpr-demo",
        "main",
        "main.weave",
        function_id,
    )

    assert before["identity_status"] == "present"
    assert after["identity_status"] == "present"
    assert after["node_id"] == function_id
    assert after["name"] == "beta"


def test_deletion_invalidates_identity(sexpr_workspace):
    created = _program(sexpr_workspace)
    added = _add_function(sexpr_workspace, created["node_id"], "gone", "fn")
    function_id = added["aliases"]["fn"]
    sexpr_workspace.delete_node(
        "sexpr-demo",
        "main",
        "main.weave",
        function_id,
    )

    status = EntityCatalogService(sexpr_workspace).inspect_identity(
        "sexpr-demo",
        "main",
        "main.weave",
        function_id,
    )
    assert status["identity_status"] == "invalid"
    assert status["reason"] == "deleted_or_absent"


def test_duplicate_declaration_names_are_ambiguous(sexpr_workspace):
    created = _program(sexpr_workspace)
    _add_function(sexpr_workspace, created["node_id"], "dup", "left")
    _add_function(sexpr_workspace, created["node_id"], "dup", "right")
    catalog = EntityCatalogService(sexpr_workspace)
    listed = catalog.list_entities("sexpr-demo", "main", "main.weave", head="fn")

    assert listed["count"] == 2
    with pytest.raises(ValidationError) as captured:
        catalog.inspect_entity(
            "sexpr-demo",
            "main",
            "main.weave",
            kind="fn",
            name="dup",
        )
    assert captured.value.code == "AMBIGUOUS_TARGET"
    assert len(captured.value.details["matches"]) == 2


def test_missing_name_lookup_is_explicit(sexpr_workspace):
    _program(sexpr_workspace)
    with pytest.raises(ValidationError) as captured:
        EntityCatalogService(sexpr_workspace).inspect_entity(
            "sexpr-demo",
            "main",
            "main.weave",
            kind="fn",
            name="missing",
        )
    assert captured.value.code == "MISSING_STRUCTURAL_TARGET"
