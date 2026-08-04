from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

import weave_frontend.artifact_quarantine_cli as cli_module

_RESULT = {
    "format": "weave-artifact-quarantine-v1",
    "complete": True,
    "mutation": "quarantine",
    "deletion": "none",
    "quarantine_id": "a" * 64,
}
_POLICY = {
    "format": "weave-artifact-retention-policy-v1",
    "reconciliation_id": "b" * 64,
    "rules": [],
}
_PLAN = {
    "format": "weave-artifact-retention-plan-v1",
    "plan_id": "c" * 64,
}


def test_cli_emits_quarantine_evidence_and_closes_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    policy_path = tmp_path / "policy.json"
    plan_path = tmp_path / "plan.json"
    policy_path.write_text(json.dumps(_POLICY), encoding="utf-8")
    plan_path.write_text(json.dumps(_PLAN), encoding="utf-8")
    closed: list[bool] = []
    calls: list[tuple[dict[str, Any], dict[str, Any], str]] = []

    def generate(
        policy: dict[str, Any],
        plan: dict[str, Any],
        *,
        entry_id: str,
    ) -> dict[str, Any]:
        calls.append((policy, plan, entry_id))
        return _RESULT

    monkeypatch.setattr(cli_module, "generate_quarantine", generate)
    monkeypatch.setattr(
        cli_module,
        "close_runtime_services",
        lambda: closed.append(True),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weave-artifact-quarantine",
            "--policy",
            str(policy_path),
            "--plan",
            str(plan_path),
            "--entry-id",
            "d" * 64,
        ],
    )

    cli_module.main()

    captured = capsys.readouterr()
    assert json.loads(captured.out) == _RESULT
    assert captured.err == ""
    assert calls == [(_POLICY, _PLAN, "d" * 64)]
    assert closed == [True]


def test_cli_rejects_two_standard_input_documents_and_closes_runtime(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
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
            "weave-artifact-quarantine",
            "--policy",
            "-",
            "--plan",
            "-",
            "--entry-id",
            "d" * 64,
        ],
    )

    with pytest.raises(SystemExit) as captured_exit:
        cli_module.main()

    captured = capsys.readouterr()
    assert captured_exit.value.code == 2
    assert captured.out == ""
    error = json.loads(captured.err)
    assert error["ok"] is False
    assert error["error"]["code"] == "ARTIFACT_QUARANTINE_INPUT_CONFLICT"
    assert closed == [True]


def test_console_script_exposes_operator_quarantine() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["scripts"]["weave-artifact-quarantine"] == (
        "weave_frontend.artifact_quarantine_cli:main"
    )
