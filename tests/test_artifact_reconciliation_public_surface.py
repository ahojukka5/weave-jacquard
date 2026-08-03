from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

import weave_frontend.artifact_reconciliation_cli as cli_module
import weave_frontend.mcp_artifact_storage as artifact_module
from weave_frontend.errors import ValidationError

_REPORT = {
    "format": "weave-artifact-reconciliation-v1",
    "complete": True,
    "reconciliation_id": "a" * 64,
    "aggregate": {
        "counts": {
            "reachable": 0,
            "orphaned": 0,
            "missing": 0,
            "corrupt": 0,
            "staging": 0,
            "quarantined": 0,
            "lock_internal": 0,
            "unknown": 0,
        }
    },
}


class _ReportService:
    def __init__(self, report: dict[str, Any] | None = None) -> None:
        self._report = report or _REPORT

    def report(self) -> dict[str, Any]:
        return self._report


class _InvalidReportService:
    def report(self) -> dict[str, Any]:
        raise ValidationError(
            "ARTIFACT_RECONCILIATION_DATABASE_INVALID",
            "database integrity failed",
        )


def test_mcp_reconciliation_report_returns_path_redacted_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        artifact_module,
        "artifact_reconciliation",
        lambda: _ReportService(),
    )

    response = artifact_module.artifact_reconciliation_report()

    assert response == {"ok": True, "result": _REPORT}
    assert "path" not in json.dumps(response)


def test_mcp_reconciliation_report_returns_structured_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        artifact_module,
        "artifact_reconciliation",
        _InvalidReportService,
    )

    response = artifact_module.artifact_reconciliation_report()

    assert response["ok"] is False
    assert response["error"]["code"] == (
        "ARTIFACT_RECONCILIATION_DATABASE_INVALID"
    )


def test_cli_emits_report_and_closes_runtime(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    closed: list[bool] = []
    monkeypatch.setattr(cli_module, "generate_report", lambda: _REPORT)
    monkeypatch.setattr(
        cli_module,
        "close_runtime_services",
        lambda: closed.append(True),
    )
    monkeypatch.setattr(sys, "argv", ["weave-artifact-reconcile"])

    cli_module.main()

    captured = capsys.readouterr()
    assert json.loads(captured.out) == _REPORT
    assert captured.err == ""
    assert closed == [True]


def test_cli_emits_structured_error_and_closes_runtime(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    closed: list[bool] = []

    def reject() -> dict[str, Any]:
        raise ValidationError(
            "ARTIFACT_RECONCILIATION_DATABASE_INVALID",
            "database integrity failed",
        )

    monkeypatch.setattr(cli_module, "generate_report", reject)
    monkeypatch.setattr(
        cli_module,
        "close_runtime_services",
        lambda: closed.append(True),
    )
    monkeypatch.setattr(sys, "argv", ["weave-artifact-reconcile"])

    with pytest.raises(SystemExit) as captured_exit:
        cli_module.main()

    captured = capsys.readouterr()
    assert captured_exit.value.code == 2
    assert captured.out == ""
    error = json.loads(captured.err)
    assert error["ok"] is False
    assert error["error"] == {
        "code": "ARTIFACT_RECONCILIATION_DATABASE_INVALID",
        "message": "database integrity failed",
        "node_id": None,
    }
    assert closed == [True]


def test_public_manifests_and_console_script_expose_reconciliation() -> None:
    from weave_jacquard.mcp_build import (
        PUBLIC_APPLICATION_MANIFEST,
        PUBLIC_TOOL_MANIFEST,
    )

    tool_name = "artifact_reconciliation_report"
    assert tool_name in PUBLIC_TOOL_MANIFEST["tool_names"]
    assert (
        PUBLIC_APPLICATION_MANIFEST["tool_count"]
        == len(PUBLIC_TOOL_MANIFEST["tool_names"])
    )
    assert (
        PUBLIC_APPLICATION_MANIFEST["tool_manifest_id"]
        == PUBLIC_TOOL_MANIFEST["tool_manifest_id"]
    )

    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["scripts"]["weave-artifact-reconcile"] == (
        "weave_frontend.artifact_reconciliation_cli:main"
    )
