from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from weave_frontend import manifest_compatibility_cli as cli
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
