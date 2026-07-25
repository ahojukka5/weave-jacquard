from __future__ import annotations

import hashlib

from weave_frontend.sexpr import parse_source
from weave_frontend.source_map import render_with_node_map, smallest_node_for_span


def test_annotated_agent_view_renders_canonical_compiler_source() -> None:
    root = parse_source(
        """(@n_root
  (program
    (@n_name (name \"demo\"))
    (@n_version (version \"0.1\"))
    (@n_entry
      (entry main
        (@n_params (params))
        (@n_returns (returns i32))
        (@n_body (do (return (const_i32 42))))))))
"""
    )

    source, node_map = render_with_node_map(
        root,
        revision_id="revision-1",
        document="main.weave",
    )

    assert "@n_" not in source
    assert source.startswith("(program")
    assert source.endswith("\n")
    assert node_map["format"] == "weave-node-map-v1"
    assert node_map["revision_id"] == "revision-1"
    assert node_map["source_sha256"] == hashlib.sha256(source.encode()).hexdigest()
    assert {span["node_id"] for span in node_map["nodes"]} >= {
        "n_root",
        "n_name",
        "n_version",
        "n_entry",
        "n_params",
        "n_returns",
        "n_body",
    }


def test_smallest_node_is_selected_for_compiler_span() -> None:
    root = parse_source(
        """(@n_root
  (program
    (@n_entry
      (entry main
        (@n_params (params))
        (@n_returns (returns i32))
        (@n_body (do (@n_return (return (const_i32 42))))))))
"""
    )
    _, node_map = render_with_node_map(
        root,
        revision_id="revision-1",
        document="main.weave",
    )
    return_span = next(
        span for span in node_map["nodes"] if span["node_id"] == "n_return"
    )

    assert (
        smallest_node_for_span(
            node_map,
            start_byte=int(return_span["start_byte"]),
            end_byte=int(return_span["end_byte"]),
        )
        == "n_return"
    )
