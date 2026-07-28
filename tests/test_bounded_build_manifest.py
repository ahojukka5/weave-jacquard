from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from weave_frontend.compiler_artifacts import (
    MAX_BUILD_MANIFEST_BYTES,
    CompilerArtifactMixin,
)
from weave_frontend.errors import ValidationError


BUILD_ID = "a" * 32


def _manifest(directory: Path, *, padding: int = 0) -> dict[str, object]:
    artifact = directory / "diagnostics.json"
    artifact.write_bytes(b"{}")
    return {
        "format": "weave-frontend-build-manifest-v2",
        "build_id": BUILD_ID,
        "status": "failed",
        "build_key_format": "legacy-build-key",
        "returncode": 1,
        "compiler_diagnostics_protocol_valid": False,
        "artifacts": {"diagnostics": artifact.name},
        "artifact_sha256": {
            artifact.name: hashlib.sha256(artifact.read_bytes()).hexdigest(),
        },
        "padding": "x" * padding,
    }


def _encoded_with_size(directory: Path, size: int) -> bytes:
    base = _manifest(directory)
    encoded = json.dumps(base, sort_keys=True, separators=(",", ":")).encode("utf-8")
    padding = size - len(encoded)
    assert padding >= 0
    base["padding"] = "x" * padding
    result = json.dumps(base, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert len(result) == size
    return result


def test_build_manifest_accepts_exact_byte_limit(tmp_path: Path) -> None:
    directory = tmp_path / BUILD_ID
    directory.mkdir()
    (directory / "manifest.json").write_bytes(
        _encoded_with_size(directory, MAX_BUILD_MANIFEST_BYTES)
    )

    result = CompilerArtifactMixin._read_verified_manifest(
        directory,
        expected_build_id=BUILD_ID,
    )

    assert result["build_id"] == BUILD_ID


def test_build_manifest_rejects_limit_plus_one(tmp_path: Path) -> None:
    directory = tmp_path / BUILD_ID
    directory.mkdir()
    (directory / "manifest.json").write_bytes(
        _encoded_with_size(directory, MAX_BUILD_MANIFEST_BYTES + 1)
    )

    with pytest.raises(ValidationError) as captured:
        CompilerArtifactMixin._read_verified_manifest(directory)

    assert captured.value.code == "INVALID_BUILD_MANIFEST"
    assert "exceeds" in captured.value.message


def test_build_manifest_rejects_symlink(tmp_path: Path) -> None:
    directory = tmp_path / BUILD_ID
    directory.mkdir()
    target = tmp_path / "outside.json"
    target.write_text(json.dumps(_manifest(directory)), encoding="utf-8")
    (directory / "manifest.json").symlink_to(target)

    with pytest.raises(ValidationError) as captured:
        CompilerArtifactMixin._read_verified_manifest(directory)

    assert captured.value.code == "INVALID_BUILD_MANIFEST"
    assert "symlink" in captured.value.message


def test_build_manifest_rejects_non_regular_file(tmp_path: Path) -> None:
    directory = tmp_path / BUILD_ID
    directory.mkdir()
    (directory / "manifest.json").mkdir()

    with pytest.raises(ValidationError) as captured:
        CompilerArtifactMixin._read_verified_manifest(directory)

    assert captured.value.code == "INVALID_BUILD_MANIFEST"
    assert "regular file" in captured.value.message
