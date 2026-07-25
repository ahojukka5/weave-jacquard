from __future__ import annotations

from weave_frontend import source_map
from weave_frontend.sexpr import make_atom, make_form, render_node, walk_nodes


def _constant(value: int):
    node = make_form("const_i32")
    node["children"].append(make_atom("integer", value))
    return node


def _deep_expression(depth: int):
    expression = _constant(0)
    for value in range(1, depth + 1):
        parent = make_form("add_i32")
        parent["children"].extend([expression, _constant(value)])
        expression = parent
    return expression


def test_source_map_rendering_bounds_flat_layout_work(monkeypatch) -> None:
    root = _deep_expression(400)
    node_count = sum(1 for _ in walk_nodes(root))
    calls = 0
    original = source_map._render_atom

    def counted(node):
        nonlocal calls
        calls += 1
        return original(node)

    monkeypatch.setattr(source_map, "_render_atom", counted)
    rendered, node_map = source_map.render_with_node_map(
        root,
        revision_id="revision-deep",
        document="deep.weave",
    )

    assert rendered == render_node(root) + "\n"
    assert len(node_map["nodes"]) == node_count
    assert calls < node_count * 12
