from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

import weave_frontend.artifact_quarantine_lifecycle_cli as cli_module

_VERIFICATION = {
    "format": "weave-artifact-quarantine-verification-v1",
    "complete": True,
    "mutation": "none",
    "verification_id": "a" * 64,
}
_BATCH = {
    "format": "weave-artifact-quarantine-delete-batch-v1",
    "complete": True,
    "batch_id": "b" * 64,
}


def test_verification_cli_emits_evidence_and_closes_runtime(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    closed: list[bool] = []
    calls: list[dict[str, Any]] = []

    def generate(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return _VERIFICATION

    monkeypatch.setattr(cli_module, "generate_verification", generate)
    monkeypatch.setattr(
        cli_module,
        "close_runtime_services",
        lambda: closed.append(True),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weave-artifact-quarantine-verify",
            "--quarantine-id",
            "1" * 64,
            "--manifest-id",
            "2" * 64,
            "--plan-id",
            "3" * 64,
            "--minimum-holding-seconds",
            "3600",
            "--as-of-unix-ns",
            "4000000000000",
        ],
    )

    cli_module.verification_main()

    captured = capsys.readouterr()
    assert json.loads(captured.out) == _VERIFICATION
    assert captured.err == ""
    assert calls == [
        {
            "quarantine_id": "1" * 64,
            "manifest_id": "2" * 64,
            "plan_id": "3" * 64,
            "minimum_holding_seconds": 3600,
            "as_of_unix_ns": 4_000_000_000_000,
        }
    ]
    assert closed == [True]


def test_delete_cli_reports_partial_batch_with_nonzero_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_path = tmp_path / "delete.json"
    entries = [
        {
            "quarantine_id": "1" * 64,
            "manifest_id": "2" * 64,
            "plan_id": "3" * 64,
            "verification_id": "4" * 64,
            "minimum_holding_seconds": 3600,
            "as_of_unix_ns": 4_000_000_000_000,
        }
    ]
    request_path.write_text(
        json.dumps(
            {
                "format": cli_module.ARTIFACT_QUARANTINE_DELETE_REQUEST_FORMAT,
                "entries": entries,
            }
        ),
        encoding="utf-8",
    )
    closed: list[bool] = []
    calls: list[list[dict[str, Any]]] = []
    partial = {**_BATCH, "complete": False, "failed": 1}

    def generate(value: list[dict[str, Any]]) -> dict[str, Any]:
        calls.append(value)
        return partial

    monkeypatch.setattr(cli_module, "generate_delete_batch", generate)
    monkeypatch.setattr(
        cli_module,
        "close_runtime_services",
        lambda: closed.append(True),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weave-artifact-quarantine-delete",
            "--request",
            str(request_path),
        ],
    )

    with pytest.raises(SystemExit) as captured_exit:
        cli_module.delete_main()

    captured = capsys.readouterr()
    assert captured_exit.value.code == 3
    assert json.loads(captured.out) == partial
    assert captured.err == ""
    assert calls == [entries]
    assert closed == [True]


def test_console_scripts_expose_verification_and_guarded_delete() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["scripts"]["weave-artifact-quarantine-verify"] == (
        "weave_frontend.artifact_quarantine_lifecycle_cli:verification_main"
    )
    assert project["project"]["scripts"]["weave-artifact-quarantine-delete"] == (
        "weave_frontend.artifact_quarantine_lifecycle_cli:delete_main"
    )
