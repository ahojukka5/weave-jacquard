from __future__ import annotations

import json
from pathlib import Path

from weave_frontend.compiler_diagnostics import collect_build_diagnostics


def _node_map(document: str, node_id: str) -> dict[str, object]:
    return {
        "format": "weave-node-map-v1",
        "source_sha256": "unused",
        "revision_id": "revision-1",
        "document": document,
        "nodes": [
            {
                "node_id": node_id,
                "start_byte": 0,
                "end_byte": 20,
                "start_line": 1,
                "start_column": 1,
                "end_line": 1,
                "end_column": 21,
            }
        ],
    }


def _entry(source: str) -> dict[str, object]:
    return {
        "code": "backend.example",
        "severity": "error",
        "phase": "backend",
        "message": "example",
        "source": source,
        "span_origin": "compiler-test",
        "span": {
            "start_byte": 2,
            "end_byte": 4,
            "start_line": 1,
            "start_column": 3,
            "end_line": 1,
            "end_column": 5,
        },
    }


def _document(entries: list[dict[str, object]]) -> dict[str, object]:
    return {
        "format": "weavec-diagnostics-v1",
        "status": "failed",
        "phase": "backend",
        "exit_code": 11,
        "raw_exit_code": 1,
        "diagnostics": entries,
    }


def test_each_compiler_source_uses_its_own_node_map(tmp_path: Path) -> None:
    main = tmp_path / "000-main.weave"
    library = tmp_path / "001-library.weave"
    main.write_text("abcdefghijklmnopqrst", encoding="utf-8")
    library.write_text("ABCDEFGHIJKLMNOPQRST", encoding="utf-8")
    raw = tmp_path / "compiler-diagnostics.json"
    raw.write_text(
        json.dumps(_document([_entry(str(main)), _entry(str(library))])),
        encoding="utf-8",
    )

    result, valid = collect_build_diagnostics(
        raw,
        canonical_sources=[
            (main, _node_map("main.weave", "n_main")),
            (library, _node_map("library.weave", "n_library")),
        ],
        returncode=11,
        timed_out=False,
        stdout="",
        stderr="",
    )

    assert valid is True
    assert [entry["document"] for entry in result["entries"]] == [
        "main.weave",
        "library.weave",
    ]
    assert [entry["node_id"] for entry in result["entries"]] == [
        "n_main",
        "n_library",
    ]


def test_relative_compiler_source_uses_unique_indexed_basename(tmp_path: Path) -> None:
    source_directory = tmp_path / "sources"
    source_directory.mkdir()
    main = source_directory / "000-main.weave"
    library = source_directory / "001-library.weave"
    main.write_text("abcdefghijklmnopqrst", encoding="utf-8")
    library.write_text("ABCDEFGHIJKLMNOPQRST", encoding="utf-8")
    raw = tmp_path / "compiler-diagnostics.json"
    raw.write_text(
        json.dumps(_document([_entry("sources/001-library.weave")])),
        encoding="utf-8",
    )

    result, valid = collect_build_diagnostics(
        raw,
        canonical_sources=[
            (main, _node_map("main.weave", "n_main")),
            (library, _node_map("library.weave", "n_library")),
        ],
        returncode=11,
        timed_out=False,
        stdout="",
        stderr="",
    )

    assert valid is True
    assert result["entries"][0]["document"] == "library.weave"
    assert result["entries"][0]["node_id"] == "n_library"


def test_noncanonical_source_remains_unmapped(tmp_path: Path) -> None:
    main = tmp_path / "000-main.weave"
    main.write_text("abcdefghijklmnopqrst", encoding="utf-8")
    raw = tmp_path / "compiler-diagnostics.json"
    raw.write_text(
        json.dumps(_document([_entry("generated.wir")])),
        encoding="utf-8",
    )

    result, valid = collect_build_diagnostics(
        raw,
        canonical_sources=[(main, _node_map("main.weave", "n_main"))],
        returncode=11,
        timed_out=False,
        stdout="",
        stderr="",
    )

    assert valid is True
    assert result["entries"][0]["document"] is None
    assert result["entries"][0]["node_id"] is None
