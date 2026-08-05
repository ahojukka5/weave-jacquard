from __future__ import annotations

import json
from pathlib import Path

from weave_frontend.artifact_storage_lifecycle import (
    ARTIFACT_STORAGE_LIFECYCLE_FORMAT,
    ArtifactLifecycleStorageService,
)


def test_lifecycle_storage_distinguishes_retained_and_quarantined_bytes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    (root / "live.bin").write_bytes(b"abc")
    capsule = root / f".quarantine-{'a' * 64}"
    payload = capsule / "payload"
    payload.mkdir(parents=True)
    (payload / "data.bin").write_bytes(b"12345")
    (capsule / "quarantine-intent.json").write_bytes(b"{}\n")
    (capsule / "quarantine-manifest.json").write_bytes(b"{}\n")
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"not-counted")
    (payload / "external-link").symlink_to(outside)

    report = ArtifactLifecycleStorageService({"builds": root}).report()

    assert report["lifecycle_format"] == ARTIFACT_STORAGE_LIFECYCLE_FORMAT
    assert report["aggregate"]["logical_bytes"] == 14
    assert report["usage"] == {
        "retained_logical_bytes": 3,
        "quarantined_logical_bytes": 11,
    }
    assert report["families"][0]["usage"] == report["usage"]
    assert (
        report["usage"]["retained_logical_bytes"] + report["usage"]["quarantined_logical_bytes"]
        == report["aggregate"]["logical_bytes"]
    )
    encoded = json.dumps(report, sort_keys=True)
    assert str(root) not in encoded
    assert str(outside) not in encoded


def test_noncanonical_quarantine_like_name_remains_retained(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    candidate = root / ".quarantine-not-an-identity"
    candidate.mkdir()
    (candidate / "payload.bin").write_bytes(b"payload")

    report = ArtifactLifecycleStorageService({"builds": root}).report()

    assert report["usage"] == {
        "retained_logical_bytes": len(b"payload"),
        "quarantined_logical_bytes": 0,
    }
