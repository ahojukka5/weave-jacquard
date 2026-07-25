from __future__ import annotations

from weave_frontend.sexpr import make_atom, make_form, parse_source, render_node
from weave_frontend.source_map import render_with_node_map


def _append(parent, child):
    parent["children"].append(child)
    return child


def _deep_program(depth: int):
    root = make_form("program")
    name = _append(root, make_form("name"))
    _append(name, make_atom("string", "deep-render"))
    version = _append(root, make_form("version"))
    _append(version, make_atom("string", "0.1"))

    entry = _append(root, make_form("entry"))
    _append(entry, make_atom("symbol", "main"))
    _append(entry, make_form("params"))
    returns = _append(entry, make_form("returns"))
    _append(returns, make_atom("symbol", "i32"))
    body = _append(entry, make_form("do"))
    statement = _append(body, make_form("return"))

    expression = make_form("const_i32")
    _append(expression, make_atom("integer", 1))
    for _ in range(depth):
        outer = make_form("add_i32")
        _append(outer, expression)
        constant = make_form("const_i32")
        _append(constant, make_atom("integer", 1))
        _append(outer, constant)
        expression = outer
    _append(statement, expression)
    return root


def test_plain_renderer_matches_compiler_source_renderer():
    root = _deep_program(100)

    rendered = render_node(root)
    compiler_source, _ = render_with_node_map(
        root,
        revision_id="revision",
        document="main.weave",
    )

    assert rendered + "\n" == compiler_source


def test_deep_plain_render_is_bounded_and_round_trips():
    rendered = render_node(_deep_program(400))

    assert len(rendered) < 600_000
    assert render_node(parse_source(rendered)) == rendered


def test_annotated_rendering_still_exposes_node_ids():
    function = make_form("fn")
    _append(function, make_atom("symbol", "main"))

    rendered = render_node(function, annotated=True, annotate_atoms=True)

    assert f"@{function['id']}" in rendered
