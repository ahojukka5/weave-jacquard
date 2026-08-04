from __future__ import annotations

import json
from pathlib import Path

from weave_frontend.compiler_diagnostics import collect_build_diagnostics


def _node_map() -> dict[str, object]:
    return {
        "format": "weave-node-map-v1",
        "source_sha256": "unused-in-this-unit-test",
        "revision_id": "revision-1",
        "document": "main.weave",
        "nodes": [
            {
                "node_id": "n_root",
                "start_byte": 0,
                "end_byte": 20,
                "start_line": 1,
                "start_column": 1,
                "end_line": 1,
                "end_column": 21,
            },
            {
                "node_id": "n_name",
                "start_byte": 9,
                "end_byte": 13,
                "start_line": 1,
                "start_column": 10,
                "end_line": 1,
                "end_column": 14,
            },
        ],
    }


def _document(entry: dict[str, object] | None, *, status: str, exit_code: int) -> dict:
    return {
        "format": "weavec-diagnostics-v1",
        "status": status,
        "phase": "complete" if exit_code == 0 else "backend",
        "exit_code": exit_code,
        "raw_exit_code": 0 if exit_code == 0 else 1,
        "diagnostics": [] if entry is None else [entry],
    }


def _entry(
    *,
    source: str | None,
    span: dict[str, int] | None,
    span_origin: str | None = None,
) -> dict[str, object]:
    return {
        "code": "backend.example",
        "severity": "error",
        "phase": "backend",
        "message": "example diagnostic",
        "source": source,
        "span_origin": (
            span_origin
            if span_origin is not None
            else ("inferred-unique-token" if span is not None else "none")
        ),
        "span": span,
    }


def _span() -> dict[str, int]:
    return {
        "start_byte": 9,
        "end_byte": 13,
        "start_line": 1,
        "start_column": 10,
        "end_line": 1,
        "end_column": 14,
    }


def test_canonical_span_maps_to_smallest_node(tmp_path: Path) -> None:
    source = tmp_path / "program.weave"
    source.write_text("(program name value)\n", encoding="utf-8")
    diagnostics_path = tmp_path / "compiler-diagnostics.json"
    diagnostics_path.write_text(
        json.dumps(
            _document(
                _entry(source=str(source), span=_span()),
                status="failed",
                exit_code=11,
            )
        ),
        encoding="utf-8",
    )

    result, valid = collect_build_diagnostics(
        diagnostics_path,
        node_map=_node_map(),
        canonical_source_path=source,
        returncode=11,
        timed_out=False,
        stdout="",
        stderr="",
    )

    assert valid is True
    assert result["entries"][0]["node_id"] == "n_name"
    assert result["entries"][0]["source"] == "program.weave"
    assert result["entries"][0]["compiler_source"] == "program.weave"


def test_propagated_wir_span_maps_to_smallest_node(tmp_path: Path) -> None:
    source = tmp_path / "program.weave"
    source.write_text("(program name value)\n", encoding="utf-8")
    diagnostics_path = tmp_path / "compiler-diagnostics.json"
    diagnostics_path.write_text(
        json.dumps(
            _document(
                _entry(
                    source=str(source),
                    span=_span(),
                    span_origin="propagated-wir-location",
                ),
                status="failed",
                exit_code=11,
            )
        ),
        encoding="utf-8",
    )

    result, valid = collect_build_diagnostics(
        diagnostics_path,
        node_map=_node_map(),
        canonical_source_path=source,
        returncode=11,
        timed_out=False,
        stdout="",
        stderr="",
    )

    assert valid is True
    assert result["entries"][0]["span_origin"] == "propagated-wir-location"
    assert result["entries"][0]["node_id"] == "n_name"


def test_spanless_and_noncanonical_diagnostics_remain_unmapped(tmp_path: Path) -> None:
    source = tmp_path / "program.weave"
    source.write_text("(program name value)\n", encoding="utf-8")
    diagnostics_path = tmp_path / "compiler-diagnostics.json"

    for entry in (
        _entry(source=str(source), span=None),
        _entry(source="generated.wir", span=_span()),
    ):
        diagnostics_path.write_text(
            json.dumps(_document(entry, status="failed", exit_code=11)),
            encoding="utf-8",
        )
        result, valid = collect_build_diagnostics(
            diagnostics_path,
            node_map=_node_map(),
            canonical_source_path=source,
            returncode=11,
            timed_out=False,
            stdout="",
            stderr="",
        )
        assert valid is True
        assert result["entries"][0]["node_id"] is None


def test_inconsistent_compiler_document_becomes_bridge_error(tmp_path: Path) -> None:
    source = tmp_path / "program.weave"
    source.write_text("(program name value)\n", encoding="utf-8")
    diagnostics_path = tmp_path / "compiler-diagnostics.json"
    diagnostics_path.write_text(
        json.dumps(_document(None, status="succeeded", exit_code=11)),
        encoding="utf-8",
    )

    result, valid = collect_build_diagnostics(
        diagnostics_path,
        node_map=_node_map(),
        canonical_source_path=source,
        returncode=11,
        timed_out=False,
        stdout="",
        stderr="",
    )

    assert valid is False
    assert result["entries"][0]["code"] == "bridge.invalid-compiler-diagnostics"
    assert any("status does not match" in item for item in result["protocol_errors"])


def test_missing_document_reports_launch_failure(tmp_path: Path) -> None:
    source = tmp_path / "program.weave"
    source.write_text("(program name value)\n", encoding="utf-8")

    result, valid = collect_build_diagnostics(
        tmp_path / "missing.json",
        node_map=_node_map(),
        canonical_source_path=source,
        returncode=None,
        timed_out=False,
        stdout="",
        stderr="could not start",
    )

    assert valid is False
    assert result["entries"][0]["code"] == "bridge.compiler-launch-failed"
