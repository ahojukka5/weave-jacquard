from __future__ import annotations

import json
import sys

from weave_frontend import build_cli


class _Workspace:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        pass


class _Targets:
    def __init__(self, _workspace) -> None:
        pass

    def list(self, project, *, branch, revision_id):
        return [
            {
                "project": project,
                "branch": branch,
                "revision_id": revision_id,
            }
        ]


class _Validator:
    def __init__(self, _targets) -> None:
        pass

    def validate(self, project, name, *, branch, revision_id):
        return {
            "project": project,
            "name": name,
            "branch": branch,
            "revision_id": revision_id,
        }


def _forbid_bridge(*_args, **_kwargs):
    raise AssertionError("CompilerBridge must not be created for this command")


def test_target_list_does_not_create_build_root(monkeypatch, capsys) -> None:
    monkeypatch.setattr(build_cli, "SExpressionWorkspace", _Workspace)
    monkeypatch.setattr(build_cli, "BuildTargetRegistry", _Targets)
    monkeypatch.setattr(build_cli, "CompilerBridge", _forbid_bridge)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weave-build",
            "--build-root",
            "/not/writable",
            "target-list",
            "demo",
            "--revision",
            "revision-1",
        ],
    )

    build_cli.main()

    assert json.loads(capsys.readouterr().out) == [
        {
            "project": "demo",
            "branch": "main",
            "revision_id": "revision-1",
        }
    ]


def test_target_validate_does_not_create_build_root(monkeypatch, capsys) -> None:
    monkeypatch.setattr(build_cli, "SExpressionWorkspace", _Workspace)
    monkeypatch.setattr(build_cli, "BuildTargetRegistry", _Targets)
    monkeypatch.setattr(build_cli, "BuildTargetValidator", _Validator)
    monkeypatch.setattr(build_cli, "CompilerBridge", _forbid_bridge)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weave-build",
            "--build-root",
            "/not/writable",
            "target-validate",
            "demo",
            "application",
            "--branch",
            "release",
            "--revision",
            "revision-2",
        ],
    )

    build_cli.main()

    assert json.loads(capsys.readouterr().out) == {
        "project": "demo",
        "name": "application",
        "branch": "release",
        "revision_id": "revision-2",
    }
