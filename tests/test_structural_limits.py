from __future__ import annotations

from typing import Any

import pytest

from weave_frontend import ValidationError
from weave_frontend import sexpr as sexpr_module
from weave_frontend import source_map as source_map_module
from weave_frontend.sexpr import make_atom, parse_source, render_node, validate_tree
from weave_frontend.source_map import render_with_node_map


def _atom(node_id: str, value: str) -> dict[str, Any]:
    return {"id": node_id, "kind": "string", "value": value}


def _list(node_id: str, children: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": node_id, "kind": "list", "children": children}


def test_validate_tree_rejects_non_object_root() -> None:
    with pytest.raises(ValidationError) as raised:
        validate_tree([])  # type: ignore[arg-type]

    assert raised.value.code == "INVALID_NODE"


def test_parse_rejects_oversized_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sexpr_module, "MAX_SOURCE_BYTES", 8)

    with pytest.raises(ValidationError) as raised:
        parse_source("123456789")

    assert raised.value.code == "SOURCE_TOO_LARGE"


def test_parse_rejects_excessive_depth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sexpr_module, "MAX_TREE_DEPTH", 2)

    with pytest.raises(ValidationError) as raised:
        parse_source("(((value)))")

    assert raised.value.code == "TREE_TOO_DEEP"


def test_parse_rejects_excessive_node_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sexpr_module, "MAX_TREE_NODES", 3)

    with pytest.raises(ValidationError) as raised:
        parse_source("(a b c)")

    assert raised.value.code == "TREE_TOO_LARGE"


def test_atom_rejects_oversized_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sexpr_module, "MAX_ATOM_VALUE_BYTES", 3)

    with pytest.raises(ValidationError) as raised:
        make_atom("string", "four")

    assert raised.value.code == "ATOM_VALUE_TOO_LARGE"


def test_float_atom_limit_uses_canonical_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sexpr_module, "MAX_ATOM_VALUE_BYTES", 2)

    with pytest.raises(ValidationError) as raised:
        make_atom("float", 1)

    assert raised.value.code == "ATOM_VALUE_TOO_LARGE"


def test_tree_rejects_aggregate_atom_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sexpr_module, "MAX_ATOM_VALUE_BYTES", 10)
    monkeypatch.setattr(sexpr_module, "MAX_TREE_VALUE_BYTES", 3)
    root = _list("n_root", [_atom("n_left", "ab"), _atom("n_right", "cd")])

    with pytest.raises(ValidationError) as raised:
        validate_tree(root)

    assert raised.value.code == "TREE_VALUE_BYTES_EXCEEDED"
    assert raised.value.node_id == "n_right"


def test_plain_render_rejects_oversized_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sexpr_module, "MAX_RENDERED_SOURCE_BYTES", 3)

    with pytest.raises(ValidationError) as raised:
        render_node(make_atom("string", "ab"))

    assert raised.value.code == "RENDERED_SOURCE_TOO_LARGE"


def test_source_map_writer_rejects_before_oversized_append(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(source_map_module, "MAX_RENDERED_SOURCE_BYTES", 3)

    with pytest.raises(ValidationError) as raised:
        render_with_node_map(
            make_atom("symbol", "four"),
            revision_id="revision",
            document="main.weave",
        )

    assert raised.value.code == "RENDERED_SOURCE_TOO_LARGE"


def test_source_map_preserves_canonical_float_rendering() -> None:
    atom = make_atom("float", 1)

    source, node_map = render_with_node_map(
        atom,
        revision_id="revision",
        document="main.weave",
    )

    assert source == "1.0\n"
    assert source.removesuffix("\n") == render_node(atom)
    assert node_map["nodes"][0]["end_byte"] == 3


def test_rejected_public_atom_write_does_not_advance_branch(
    sexpr_workspace: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sexpr_workspace.create_program(
        "sexpr-demo",
        "main",
        "main.weave",
        program_name="bounded",
    )
    root_id = str(
        sexpr_workspace.list_documents("sexpr-demo", "main")[0]["root_node_id"]
    )
    before = sexpr_workspace.branch_head("sexpr-demo", "main")
    monkeypatch.setattr(sexpr_module, "MAX_ATOM_VALUE_BYTES", 3)

    with pytest.raises(ValidationError) as raised:
        sexpr_workspace.add_atom(
            "sexpr-demo",
            "main",
            "main.weave",
            root_id,
            "string",
            "four",
        )

    assert raised.value.code == "ATOM_VALUE_TOO_LARGE"
    assert sexpr_workspace.branch_head("sexpr-demo", "main") == before
