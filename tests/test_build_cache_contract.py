from __future__ import annotations

import json
from pathlib import Path

from weave_frontend.compiler_bridge import BUILD_KEY_FORMAT, CompilerBridge


def _write_cached_build(
    directory: Path,
    *,
    build_key_format: str,
    protocol_valid: bool = True,
    include_compiler_diagnostics: bool = True,
) -> None:
    directory.mkdir()
    (directory / "program").write_text("executable", encoding="utf-8")
    artifacts: dict[str, str | None] = {
        "executable": "program",
        "compiler_diagnostics": (
            "compiler-diagnostics.json" if include_compiler_diagnostics else None
        ),
    }
    if include_compiler_diagnostics:
        (directory / "compiler-diagnostics.json").write_text(
            '{"format":"weavec-diagnostics-v1"}\n',
            encoding="utf-8",
        )
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "format": "weave-frontend-build-manifest-v1",
                "build_key_format": build_key_format,
                "status": "succeeded",
                "compiler_diagnostics_protocol_valid": protocol_valid,
                "artifacts": artifacts,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_cache_rejects_pre_diagnostics_contract(tmp_path: Path) -> None:
    cached = tmp_path / "cached"
    _write_cached_build(cached, build_key_format="weave-build-key-v1")

    assert CompilerBridge._read_successful_manifest(cached) is None


def test_cache_requires_valid_compiler_diagnostics_artifact(tmp_path: Path) -> None:
    invalid_protocol = tmp_path / "invalid-protocol"
    _write_cached_build(
        invalid_protocol,
        build_key_format=BUILD_KEY_FORMAT,
        protocol_valid=False,
    )
    missing_artifact = tmp_path / "missing-artifact"
    _write_cached_build(
        missing_artifact,
        build_key_format=BUILD_KEY_FORMAT,
        include_compiler_diagnostics=False,
    )

    assert CompilerBridge._read_successful_manifest(invalid_protocol) is None
    assert CompilerBridge._read_successful_manifest(missing_artifact) is None


def test_cache_accepts_current_diagnostics_contract(tmp_path: Path) -> None:
    cached = tmp_path / "cached"
    _write_cached_build(cached, build_key_format=BUILD_KEY_FORMAT)

    manifest = CompilerBridge._read_successful_manifest(cached)

    assert manifest is not None
    assert manifest["build_key_format"] == BUILD_KEY_FORMAT
    assert manifest["artifact_paths"]["compiler_diagnostics"].endswith(
        "compiler-diagnostics.json"
    )
