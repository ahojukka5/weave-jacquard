from __future__ import annotations

import json
from pathlib import Path

import pytest

from weave_frontend.errors import ArtifactIntegrityError
from weave_frontend.mcp_merge_candidate_test_runs import merge_candidate_builds
from weave_frontend.verified_merge_candidate_build import (
    MAX_MERGE_CANDIDATE_BUILD_MANIFEST_BYTES,
    MergeCandidateBuildService,
)


def _json_object_with_size(size: int) -> bytes:
    base = {"padding": ""}
    encoded = json.dumps(base, separators=(",", ":")).encode("utf-8")
    padding = size - len(encoded)
    assert padding >= 0
    base["padding"] = "x" * padding
    result = json.dumps(base, separators=(",", ":")).encode("utf-8")
    assert len(result) == size
    return result


def test_production_factory_uses_verified_candidate_build_service() -> None:
    assert merge_candidate_builds.__annotations__["return"] == "MergeCandidateBuildService"


def test_candidate_build_manifest_accepts_exact_limit(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_bytes(_json_object_with_size(MAX_MERGE_CANDIDATE_BUILD_MANIFEST_BYTES))

    result = MergeCandidateBuildService._read_manifest(path)

    assert isinstance(result["padding"], str)


def test_candidate_build_manifest_rejects_limit_plus_one(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_bytes(
        _json_object_with_size(MAX_MERGE_CANDIDATE_BUILD_MANIFEST_BYTES + 1)
    )

    with pytest.raises(ArtifactIntegrityError, match="exceeds"):
        MergeCandidateBuildService._read_manifest(path)


def test_candidate_build_manifest_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    path = tmp_path / "manifest.json"
    path.symlink_to(target)

    with pytest.raises(ArtifactIntegrityError, match="symlink"):
        MergeCandidateBuildService._read_manifest(path)


def test_candidate_build_manifest_rejects_non_regular_file(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.mkdir()

    with pytest.raises(ArtifactIntegrityError, match="regular file"):
        MergeCandidateBuildService._read_manifest(path)
