from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from weave_frontend.build_inspection import BuildInspectionService
from weave_frontend.errors import ValidationError


class _Bridge:
    def __init__(self, diagnostics: Path) -> None:
        self.diagnostics = diagnostics
        self.calls: list[str] = []

    def get(self, build_id: str) -> dict[str, Any]:
        self.calls.append(build_id)
        return {
            "build_id": build_id,
            "status": "failed",
            "revision_id": "revision-1",
            "project": "demo",
            "branch": "main",
            "document": "main.weave",
            "documents": ["main.weave"],
            "returncode": 11,
            "artifact_paths": {"diagnostics": str(self.diagnostics)},
        }


def _write_diagnostics(path: Path, entries: list[dict[str, Any]]) -> None:
    path.write_text(
        json.dumps(
            {
                "format": "weave-build-diagnostics-v1",
                "returncode": 11,
                "timed_out": False,
                "stdout": "",
                "stderr": "backend failed\n",
                "compiler": {
                    "format": "weavec-diagnostics-v1",
                    "status": "failed",
                    "phase": "backend",
                    "exit_code": 11,
                    "raw_exit_code": 1,
                },
                "protocol_valid": True,
                "protocol_errors": [],
                "compiler_manifest": {
                    "format": "weavec-build-manifest-v1",
                    "status": "failed",
                    "phase": "backend",
                    "target": "x86_64-unknown-linux-gnu",
                },
                "compiler_manifest_protocol_valid": True,
                "compiler_manifest_errors": [],
                "entries": entries,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _entries(count: int) -> list[dict[str, Any]]:
    return [
        {
            "code": f"backend.error-{index}",
            "severity": "error",
            "phase": "backend",
            "message": f"error {index}",
            "source": "000-main.weave",
            "compiler_source": "000-main.weave",
            "document": "main.weave",
            "span_origin": "inferred-unique-token",
            "span": {
                "start_byte": index,
                "end_byte": index + 1,
                "start_line": 1,
                "start_column": index + 1,
                "end_line": 1,
                "end_column": index + 2,
            },
            "node_id": f"n_{index}",
        }
        for index in range(count)
    ]


def test_diagnostics_page_preserves_entries_and_continuation(tmp_path: Path) -> None:
    diagnostics = tmp_path / "diagnostics.json"
    entries = _entries(5)
    _write_diagnostics(diagnostics, entries)
    bridge = _Bridge(diagnostics)
    service = BuildInspectionService(bridge)

    first = service.diagnostics_page("a" * 32, limit=2)
    second = service.diagnostics_page("a" * 32, start_index=first["next_index"], limit=2)
    third = service.diagnostics_page("a" * 32, start_index=second["next_index"], limit=2)

    assert bridge.calls == ["a" * 32] * 3
    assert first["total_diagnostic_count"] == 5
    assert first["diagnostics"] == entries[:2]
    assert first["next_index"] == 2
    assert second["diagnostics"] == entries[2:4]
    assert second["next_index"] == 4
    assert third["diagnostics"] == entries[4:]
    assert third["has_more"] is False
    assert third["next_index"] is None
    assert first["protocol_valid"] is True
    assert first["protocol_error_count"] == 0
    assert first["compiler"]["phase"] == "backend"
    assert first["compiler_manifest_protocol_valid"] is True


def test_diagnostics_page_supports_empty_and_past_end_pages(tmp_path: Path) -> None:
    diagnostics = tmp_path / "diagnostics.json"
    _write_diagnostics(diagnostics, [])
    service = BuildInspectionService(_Bridge(diagnostics))

    empty = service.diagnostics_page("b" * 32)
    past_end = service.diagnostics_page("b" * 32, start_index=100)

    assert empty["total_diagnostic_count"] == 0
    assert empty["diagnostics"] == []
    assert empty["has_more"] is False
    assert past_end["returned_count"] == 0
    assert past_end["next_index"] is None


@pytest.mark.parametrize("value", [-1, True, 1.5, "0"])
def test_diagnostics_page_rejects_invalid_start_index(
    tmp_path: Path,
    value: Any,
) -> None:
    diagnostics = tmp_path / "diagnostics.json"
    _write_diagnostics(diagnostics, [])
    service = BuildInspectionService(_Bridge(diagnostics))

    with pytest.raises(ValidationError, match="start_index") as captured:
        service.diagnostics_page("c" * 32, start_index=value)
    assert captured.value.code == "INVALID_DIAGNOSTIC_INDEX"


@pytest.mark.parametrize("value", [0, 201, True, 1.5, "1"])
def test_diagnostics_page_rejects_invalid_limit(tmp_path: Path, value: Any) -> None:
    diagnostics = tmp_path / "diagnostics.json"
    _write_diagnostics(diagnostics, [])
    service = BuildInspectionService(_Bridge(diagnostics))

    with pytest.raises(ValidationError, match="limit") as captured:
        service.diagnostics_page("d" * 32, limit=value)
    assert captured.value.code == "INVALID_DIAGNOSTIC_LIMIT"


def test_diagnostics_page_rejects_invalid_format_and_entries(tmp_path: Path) -> None:
    diagnostics = tmp_path / "diagnostics.json"
    bridge = _Bridge(diagnostics)
    service = BuildInspectionService(bridge)

    diagnostics.write_text('{"format":"other","entries":[]}\n', encoding="utf-8")
    with pytest.raises(ValidationError) as format_error:
        service.diagnostics_page("e" * 32)
    assert format_error.value.code == "INVALID_BUILD_DIAGNOSTICS"

    diagnostics.write_text(
        '{"format":"weave-build-diagnostics-v1","entries":[1]}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValidationError) as entries_error:
        service.diagnostics_page("e" * 32)
    assert entries_error.value.code == "INVALID_BUILD_DIAGNOSTICS"
