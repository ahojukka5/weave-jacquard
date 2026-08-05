from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from weave_frontend import manifest_compatibility_cli as cli
from weave_frontend.runtime_evidence_compatibility import SERVICE_GRAPH_FORMAT
from weave_jacquard.manifest_compatibility_cli import main as public_main


def _tool(name: str) -> dict[str, object]:
    return {
        "name": name,
        "description": f"{name} tool",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    }


def _write_manifest(path: Path, *tools: dict[str, object]) -> None:
    path.write_text(
        json.dumps(
            {
                "format": "weave-jacquard-tool-manifest-v1",
                "tools": list(tools),
            }
        ),
        encoding="utf-8",
    )


def _application_manifest(*, variables: list[str]) -> dict[str, object]:
    return {
        "format": "weave-jacquard-application-v2",
        "capabilities": [
            {
                "name": "base",
                "module": "example.base",
                "depends_on": [],
            }
        ],
        "tool_manifest_id": "tool-id",
        "tool_count": 1,
        "configuration_variables": variables,
        "application_id": "application-id",
    }


def _write_application_manifest(
    path: Path,
    *,
    variables: list[str],
) -> None:
    path.write_text(
        json.dumps(_application_manifest(variables=variables)),
        encoding="utf-8",
    )


def _service_graph(*services: dict[str, object]) -> dict[str, object]:
    ordered = sorted(services, key=lambda item: str(item["name"]))
    payload = {
        "format": SERVICE_GRAPH_FORMAT,
        "service_count": len(ordered),
        "services": ordered,
    }
    identity = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    return {
        **payload,
        "service_graph_id": identity,
    }


def test_public_manifest_diff_cli_compares_two_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    _write_manifest(old, _tool("alpha"))
    _write_manifest(new, _tool("alpha"), _tool("beta"))
    monkeypatch.setattr(sys, "argv", ["weave-manifest-diff", str(old), str(new)])

    public_main()

    captured = capsys.readouterr()
    assert captured.err == ""
    report = json.loads(captured.out)
    assert report["classification"] == "additive-compatible"
    assert report["change_count"] == 1
    assert report["changes"][0]["kind"] == "tool-added"


def test_manifest_diff_cli_dispatches_application_manifests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    old = tmp_path / "old-application.json"
    new = tmp_path / "new-application.json"
    _write_application_manifest(old, variables=["WEAVE_DB"])
    _write_application_manifest(new, variables=["WEAVE_DB", "WEAVE_ROOT"])
    monkeypatch.setattr(sys, "argv", ["weave-manifest-diff", str(old), str(new)])

    public_main()

    captured = capsys.readouterr()
    assert captured.err == ""
    report = json.loads(captured.out)
    assert report["classification"] == "additive-compatible"
    assert report["changes"][0]["kind"] == "configuration-variable-added"


def test_manifest_diff_cli_compares_installed_application(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    old = tmp_path / "old-application.json"
    _write_application_manifest(old, variables=["WEAVE_DB"])
    monkeypatch.setattr(
        cli,
        "_installed_manifest",
        lambda kind: _application_manifest(variables=["WEAVE_DB", "WEAVE_ROOT"]),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weave-manifest-diff",
            str(old),
            "--installed",
            "application",
        ],
    )

    public_main()

    captured = capsys.readouterr()
    assert captured.err == ""
    report = json.loads(captured.out)
    assert report["classification"] == "additive-compatible"
    assert report["changes"][0]["kind"] == "configuration-variable-added"


def test_manifest_diff_cli_dispatches_service_graph_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    old = tmp_path / "old-service-graph.json"
    new = tmp_path / "new-service-graph.json"
    old.write_text(
        json.dumps(
            _service_graph(
                {
                    "name": "workspace",
                    "origin": "example.workspace",
                    "depends_on": [],
                }
            )
        ),
        encoding="utf-8",
    )
    new.write_text(
        json.dumps(
            _service_graph(
                {
                    "name": "compiler",
                    "origin": "example.compiler",
                    "depends_on": ["workspace"],
                },
                {
                    "name": "workspace",
                    "origin": "example.workspace",
                    "depends_on": [],
                },
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "argv", ["weave-manifest-diff", str(old), str(new)])

    public_main()

    captured = capsys.readouterr()
    assert captured.err == ""
    report = json.loads(captured.out)
    assert report["classification"] == "behavior-review-required"
    assert report["changes"][0]["kind"] == "service-added"


def test_manifest_diff_cli_rejects_unknown_format(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    old.write_text('{"format":"future","tools":[]}', encoding="utf-8")
    _write_manifest(new)
    monkeypatch.setattr(sys, "argv", ["weave-manifest-diff", str(old), str(new)])

    with pytest.raises(SystemExit) as exit_info:
        cli.main()

    captured = capsys.readouterr()
    assert exit_info.value.code == 2
    assert captured.out == ""
    error = json.loads(captured.err)
    assert error["error"]["code"] == "MANIFEST_COMPATIBILITY_ERROR"
    assert "unsupported old manifest format" in error["error"]["message"]


def test_manifest_diff_cli_requires_one_comparison_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    old = tmp_path / "old.json"
    _write_manifest(old)
    monkeypatch.setattr(sys, "argv", ["weave-manifest-diff", str(old)])

    with pytest.raises(SystemExit) as exit_info:
        cli.main()

    captured = capsys.readouterr()
    assert exit_info.value.code == 2
    assert captured.out == ""
    error = json.loads(captured.err)
    assert "new_manifest or --installed is required" in error["error"]["message"]


def test_manifest_diff_cli_bounds_each_input_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    old.write_bytes(b"x" * 33)
    _write_manifest(new)
    monkeypatch.setattr(cli, "MAX_MANIFEST_BYTES", 32)
    monkeypatch.setattr(sys, "argv", ["weave-manifest-diff", str(old), str(new)])

    with pytest.raises(SystemExit) as exit_info:
        cli.main()

    captured = capsys.readouterr()
    assert exit_info.value.code == 2
    assert captured.out == ""
    error = json.loads(captured.err)
    assert error["error"]["code"] == "MANIFEST_COMPATIBILITY_ERROR"
    assert "exceeds 32 bytes" in error["error"]["message"]
