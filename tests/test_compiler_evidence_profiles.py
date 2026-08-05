from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from weave_frontend.compiler import CompilerBridge, normalize_evidence_profile
from weave_frontend.errors import ValidationError
from weave_frontend.sexpr_service import SExpressionWorkspace

PROGRAM = """(program
  (name "demo")
  (version "0.1")
  (entry main
    (params)
    (returns i32)
    (do (return (const_i32 42)))))
"""


class RecordingCapabilities:
    def __init__(self, compiler_sha256: str, *, fail: bool = False) -> None:
        self.compiler_sha256 = compiler_sha256
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def require(
        self,
        *,
        command: str | None = None,
        protocols: tuple[str, ...] = (),
        target: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "command": command,
                "protocols": protocols,
                "target": target,
            }
        )
        if self.fail:
            raise ValidationError(
                "WEAVEC_PROTOCOL_UNSUPPORTED",
                "requested compiler evidence is unavailable",
            )
        return {
            "_jacquard_identity": {
                "compiler_sha256": self.compiler_sha256,
            }
        }


class IdentityBridge(CompilerBridge):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.executions = 0

    def _execute_build(self, **kwargs: Any) -> dict[str, Any]:
        self.executions += 1
        return {
            "build_id": kwargs["build_id"],
            "evidence_profile": kwargs["evidence_profile"],
        }


def _compiler(path: Path) -> tuple[Path, str]:
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return path, digest


def _workspace(tmp_path: Path, compiler: Path) -> SExpressionWorkspace:
    workspace = SExpressionWorkspace(tmp_path / "weave.db", weavec_binary=compiler)
    workspace.initialize("demo")
    workspace.import_program("demo", "main", "main.weave", PROGRAM)
    return workspace


def test_evidence_profile_validation_is_strict() -> None:
    assert normalize_evidence_profile(None) == "none"
    assert normalize_evidence_profile("minimal") == "minimal"
    assert normalize_evidence_profile("full") == "full"

    with pytest.raises(ValidationError) as captured:
        normalize_evidence_profile("everything")

    assert captured.value.code == "INVALID_EVIDENCE_PROFILE"


def test_evidence_profile_changes_build_identity(tmp_path: Path) -> None:
    compiler, compiler_sha256 = _compiler(tmp_path / "weavec")
    capabilities = RecordingCapabilities(compiler_sha256)
    with _workspace(tmp_path, compiler) as workspace:
        bridge = IdentityBridge(
            workspace,
            compiler=compiler,
            build_root=tmp_path / "builds",
            capabilities=capabilities,  # type: ignore[arg-type]
        )
        none = bridge.build("demo", "main.weave")
        minimal = bridge.build(
            "demo",
            "main.weave",
            evidence_profile="minimal",
        )
        full = bridge.build(
            "demo",
            "main.weave",
            evidence_profile="full",
        )

    assert len({none["build_id"], minimal["build_id"], full["build_id"]}) == 3
    assert [item["evidence_profile"] for item in (none, minimal, full)] == [
        "none",
        "minimal",
        "full",
    ]
    assert [call["command"] for call in capabilities.calls] == ["build", "build"]
    assert all("weavec-compilation-trace-v1" in call["protocols"] for call in capabilities.calls)


def test_capability_failure_prevents_build_execution(tmp_path: Path) -> None:
    compiler, compiler_sha256 = _compiler(tmp_path / "weavec")
    capabilities = RecordingCapabilities(compiler_sha256, fail=True)
    with _workspace(tmp_path, compiler) as workspace:
        bridge = IdentityBridge(
            workspace,
            compiler=compiler,
            build_root=tmp_path / "builds",
            capabilities=capabilities,  # type: ignore[arg-type]
        )
        with pytest.raises(ValidationError) as captured:
            bridge.build(
                "demo",
                "main.weave",
                evidence_profile="minimal",
            )

    assert captured.value.code == "WEAVEC_PROTOCOL_UNSUPPORTED"
    assert bridge.executions == 0


def test_capability_registry_must_match_selected_compiler(tmp_path: Path) -> None:
    compiler, _ = _compiler(tmp_path / "weavec")
    capabilities = RecordingCapabilities("0" * 64)
    with _workspace(tmp_path, compiler) as workspace:
        bridge = IdentityBridge(
            workspace,
            compiler=compiler,
            build_root=tmp_path / "builds",
            capabilities=capabilities,  # type: ignore[arg-type]
        )
        with pytest.raises(ValidationError) as captured:
            bridge.build(
                "demo",
                "main.weave",
                evidence_profile="full",
            )

    assert captured.value.code == "WEAVEC_CAPABILITY_COMPILER_MISMATCH"
    assert bridge.executions == 0
