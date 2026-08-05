from __future__ import annotations

import json
from pathlib import Path

import pytest

from weave_frontend.compiler import collect_build_diagnostics


def _node_map() -> dict[str, object]:
    return {
        "format": "weave-node-map-v1",
        "source_sha256": "unused",
        "revision_id": "revision-1",
        "document": "main.weave",
        "nodes": [],
    }


def _entry() -> dict[str, object]:
    return {
        "code": "backend.failed",
        "severity": "error",
        "phase": "backend",
        "message": "backend failed",
        "source": None,
        "span_origin": "none",
        "span": None,
    }


def _validate(tmp_path: Path, document: dict[str, object], *, returncode: int):
    source = tmp_path / "main.weave"
    source.write_text("(program)\n", encoding="utf-8")
    diagnostics = tmp_path / "compiler-diagnostics.json"
    diagnostics.write_text(json.dumps(document), encoding="utf-8")
    return collect_build_diagnostics(
        diagnostics,
        node_map=_node_map(),
        canonical_source_path=source,
        returncode=returncode,
        timed_out=False,
        stdout="",
        stderr="",
    )


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda value: value.update(phase="backend"), "phase must be 'complete'"),
        (lambda value: value["diagnostics"].append(_entry()), "must have no entries"),
        (lambda value: value.update(raw_exit_code=1), "raw_exit_code must be zero"),
    ],
)
def test_impossible_success_document_is_rejected(tmp_path, mutation, expected) -> None:
    document: dict[str, object] = {
        "format": "weavec-diagnostics-v1",
        "status": "succeeded",
        "phase": "complete",
        "exit_code": 0,
        "raw_exit_code": 0,
        "diagnostics": [],
    }
    mutation(document)

    result, valid = _validate(tmp_path, document, returncode=0)

    assert valid is False
    assert any(expected in error for error in result["protocol_errors"])
    assert result["entries"][0]["code"] == "bridge.invalid-compiler-diagnostics"


def test_failed_document_requires_an_error_entry(tmp_path: Path) -> None:
    document = {
        "format": "weavec-diagnostics-v1",
        "status": "failed",
        "phase": "backend",
        "exit_code": 11,
        "raw_exit_code": 1,
        "diagnostics": [],
    }

    result, valid = _validate(tmp_path, document, returncode=11)

    assert valid is False
    assert any("must contain an entry" in error for error in result["protocol_errors"])


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("severity", "warning", "severity must be 'error'"),
        ("span_origin", "guessed", "span_origin must be one of"),
    ],
)
def test_invalid_entry_metadata_is_rejected(
    tmp_path: Path,
    field: str,
    value: str,
    expected: str,
) -> None:
    entry = _entry()
    entry[field] = value
    document = {
        "format": "weavec-diagnostics-v1",
        "status": "failed",
        "phase": "backend",
        "exit_code": 11,
        "raw_exit_code": 1,
        "diagnostics": [entry],
    }

    result, valid = _validate(tmp_path, document, returncode=11)

    assert valid is False
    assert any(expected in error for error in result["protocol_errors"])


def test_span_origin_and_span_must_agree(tmp_path: Path) -> None:
    entry = _entry()
    entry["span_origin"] = "compiler-preflight"
    document = {
        "format": "weavec-diagnostics-v1",
        "status": "failed",
        "phase": "frontend",
        "exit_code": 10,
        "raw_exit_code": 1,
        "diagnostics": [entry],
    }

    result, valid = _validate(tmp_path, document, returncode=10)

    assert valid is False
    assert any("span is required" in error for error in result["protocol_errors"])
