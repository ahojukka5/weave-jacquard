from __future__ import annotations

import json
from pathlib import Path

import pytest

from weave_frontend.errors import ArtifactIntegrityError
from weave_frontend.tested_merge_attestations import (
    MAX_TESTED_MERGE_ATTESTATION_BYTES,
    TestedMergeAttestationService,
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


def test_attestation_manifest_accepts_exact_limit(tmp_path: Path) -> None:
    path = tmp_path / "attestation.json"
    path.write_bytes(_json_object_with_size(MAX_TESTED_MERGE_ATTESTATION_BYTES))

    result = TestedMergeAttestationService._read_json(path)

    assert isinstance(result["padding"], str)


def test_attestation_manifest_rejects_limit_plus_one(tmp_path: Path) -> None:
    path = tmp_path / "attestation.json"
    path.write_bytes(_json_object_with_size(MAX_TESTED_MERGE_ATTESTATION_BYTES + 1))

    with pytest.raises(ArtifactIntegrityError, match="exceeds"):
        TestedMergeAttestationService._read_json(path)


def test_attestation_manifest_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    path = tmp_path / "attestation.json"
    path.symlink_to(target)

    with pytest.raises(ArtifactIntegrityError, match="symlink"):
        TestedMergeAttestationService._read_json(path)


def test_attestation_manifest_rejects_non_regular_file(tmp_path: Path) -> None:
    path = tmp_path / "attestation.json"
    path.mkdir()

    with pytest.raises(ArtifactIntegrityError, match="regular file"):
        TestedMergeAttestationService._read_json(path)
