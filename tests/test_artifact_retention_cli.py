from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

import weave_frontend.artifact_retention_cli as cli_module

_PLAN = {
    "format": "weave-artifact-retention-plan-v1",
    "complete": True,
    "dry_run": True,
    "mutation": "none",
    "plan_id": "a" * 64,
}
_POLICY = {
    "format": "weave-artifact-retention-policy-v1",
    "reconciliation_id": "b" * 64,
    "rules": [],
}


def test_cli_emits_plan_and_closes_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(_POLICY), encoding="utf-8")
    closed: list[bool] = []
    calls: list[tuple[dict[str, Any], int]] = []

    def generate(policy: dict[str, Any], *, as_of_unix_ns: int) -> dict[str, Any]:
        calls.append((policy, as_of_unix_ns))
        return _PLAN

    monkeypatch.setattr(cli_module, "generate_plan", generate)
    monkeypatch.setattr(
        cli_module,
        "close_runtime_services",
        lambda: closed.append(True),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weave-artifact-retention-plan",
            "--policy",
            str(policy_path),
            "--as-of-unix-ns",
            "123",
        ],
    )

    cli_module.main()

    captured = capsys.readouterr()
    assert json.loads(captured.out) == _PLAN
    assert captured.err == ""
    assert calls == [(_POLICY, 123)]
    assert closed == [True]


def test_cli_emits_structured_policy_error_and_closes_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    policy_path = tmp_path / "policy.json"
    policy_path.write_text("not json", encoding="utf-8")
    closed: list[bool] = []
    monkeypatch.setattr(
        cli_module,
        "close_runtime_services",
        lambda: closed.append(True),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weave-artifact-retention-plan",
            "--policy",
            str(policy_path),
            "--as-of-unix-ns",
            "123",
        ],
    )

    with pytest.raises(SystemExit) as captured_exit:
        cli_module.main()

    captured = capsys.readouterr()
    assert captured_exit.value.code == 2
    assert captured.out == ""
    error = json.loads(captured.err)
    assert error["ok"] is False
    assert error["error"]["code"] == "ARTIFACT_RETENTION_POLICY_INVALID"
    assert closed == [True]


def test_console_script_exposes_operator_retention_plan() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["scripts"]["weave-artifact-retention-plan"] == (
        "weave_frontend.artifact_retention_cli:main"
    )
