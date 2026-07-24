from __future__ import annotations

from weave_frontend.sexpr import parse_source, render_node, walk_nodes


def test_parse_render_and_annotated_round_trip():
    root = parse_source('(program (name "demo") (fn main (params) (returns i32)))')
    canonical = render_node(root)
    annotated = render_node(root, annotated=True, annotate_atoms=True)

    assert canonical.startswith("(program")
    assert f"@{root['id']}" in annotated

    reparsed = parse_source(annotated)
    assert reparsed["id"] == root["id"]
    assert render_node(reparsed) == canonical
    assert len(list(walk_nodes(reparsed))) == len(list(walk_nodes(root)))
