from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

import weave_frontend.artifacts.quarantine.restoration_cli as cli_module

_RESULT = {
    "format": "weave-artifact-quarantine-restore-result-v1",
    "complete": True,
    "mutation": "restore",
    "restore_id": "a" * 64,
}


def test_cli_emits_restore_evidence_and_closes_runtime(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    closed: list[bool] = []
    calls: list[tuple[str, str]] = []

    def generate(*, quarantine_id: str, manifest_id: str) -> dict[str, Any]:
        calls.append((quarantine_id, manifest_id))
        return _RESULT

    monkeypatch.setattr(cli_module, "generate_restore", generate)
    monkeypatch.setattr(
        cli_module,
        "close_runtime_services",
        lambda: closed.append(True),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weave-artifact-quarantine-restore",
            "--quarantine-id",
            "b" * 64,
            "--manifest-id",
            "c" * 64,
        ],
    )

    cli_module.main()

    captured = capsys.readouterr()
    assert json.loads(captured.out) == _RESULT
    assert captured.err == ""
    assert calls == [("b" * 64, "c" * 64)]
    assert closed == [True]


def test_cli_emits_structured_restore_error_and_closes_runtime(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    closed: list[bool] = []

    def fail(*, quarantine_id: str, manifest_id: str) -> dict[str, Any]:
        del quarantine_id, manifest_id
        raise cli_module.ValidationError(
            "ARTIFACT_QUARANTINE_RESTORE_ID_INVALID",
            "invalid restore identity",
        )

    monkeypatch.setattr(cli_module, "generate_restore", fail)
    monkeypatch.setattr(
        cli_module,
        "close_runtime_services",
        lambda: closed.append(True),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weave-artifact-quarantine-restore",
            "--quarantine-id",
            "bad",
            "--manifest-id",
            "bad",
        ],
    )

    with pytest.raises(SystemExit) as captured_exit:
        cli_module.main()

    captured = capsys.readouterr()
    assert captured_exit.value.code == 2
    assert captured.out == ""
    error = json.loads(captured.err)
    assert error["ok"] is False
    assert error["error"]["code"] == ("ARTIFACT_QUARANTINE_RESTORE_ID_INVALID")
    assert closed == [True]


def test_console_script_exposes_operator_quarantine_restore() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert (
        project["project"]["scripts"]["weave-artifact-quarantine-restore"]
        == "weave_frontend.artifacts.quarantine.restoration_cli:main"
    )
