from __future__ import annotations

import json
import sys

import pytest

from weave_frontend import build_cli
from weave_frontend.errors import NotFoundError, ValidationError


def test_validation_error_is_json_on_stderr(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        build_cli,
        "_execute",
        lambda _args: (_ for _ in ()).throw(
            ValidationError("INVALID_BUILD_ID", "build ID must be hexadecimal")
        ),
    )
    monkeypatch.setattr(sys, "argv", ["weave-build", "get", "invalid"])

    with pytest.raises(SystemExit) as exit_info:
        build_cli.main()

    captured = capsys.readouterr()
    assert exit_info.value.code == 2
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "ok": False,
        "error": {
            "code": "INVALID_BUILD_ID",
            "message": "build ID must be hexadecimal",
            "node_id": None,
        },
    }


def test_not_found_error_is_json_on_stderr(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        build_cli,
        "_execute",
        lambda _args: (_ for _ in ()).throw(NotFoundError("build not found")),
    )
    monkeypatch.setattr(sys, "argv", ["weave-build", "get", "deadbeef"])

    with pytest.raises(SystemExit) as exit_info:
        build_cli.main()

    captured = capsys.readouterr()
    assert exit_info.value.code == 2
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "ok": False,
        "error": {"code": "NotFoundError", "message": "build not found"},
    }
