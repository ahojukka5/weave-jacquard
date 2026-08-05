from __future__ import annotations

import os
from pathlib import Path

import pytest

from weave_frontend import artifact_retention_accounting
from weave_frontend.artifact_reconciliation import (
    RetainedArtifactInventoryService,
)
from weave_frontend.artifact_retention_accounting import (
    ArtifactRetentionAccountant,
)
from weave_frontend.errors import ValidationError


def _accountant(**kwargs: int) -> ArtifactRetentionAccountant:
    return ArtifactRetentionAccountant(
        RetainedArtifactInventoryService.__new__(RetainedArtifactInventoryService),
        max_scan_entries=100,
        **kwargs,
    )


def test_relocation_snapshot_survives_rename_and_detects_payload_change(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    payload = source / "payload.bin"
    payload.write_bytes(b"before")

    accountant = _accountant()
    before, _remaining = accountant.capture(source, 100)
    destination = tmp_path / "destination"
    os.replace(source, destination)
    moved, _remaining = accountant.capture(destination, 100)

    assert moved["relocation_snapshot_id"] == before["relocation_snapshot_id"]
    assert moved["logical_bytes"] == before["logical_bytes"]

    (destination / "payload.bin").write_bytes(b"after-longer")
    changed, _remaining = accountant.capture(destination, 100)
    assert changed["entry_snapshot_id"] != moved["entry_snapshot_id"]
    assert changed["relocation_snapshot_id"] != before["relocation_snapshot_id"]


def test_snapshot_hashes_empty_and_nested_regular_files(tmp_path: Path) -> None:
    root = tmp_path / "root"
    nested = root / "nested"
    nested.mkdir(parents=True)
    (root / "empty.bin").write_bytes(b"")
    payload = nested / "payload.bin"
    payload.write_bytes(b"payload")

    accountant = _accountant()
    first, _remaining = accountant.capture(root, 100)
    second, _remaining = accountant.capture(root, 100)

    assert first == second
    assert first["regular_files"] == 2
    assert first["directories"] == 2
    assert first["logical_bytes"] == len(b"payload")

    payload.write_bytes(b"changed")
    changed, _remaining = accountant.capture(root, 100)
    assert changed["relocation_snapshot_id"] != first["relocation_snapshot_id"]


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks unavailable")
def test_snapshot_does_not_follow_symlink_targets(tmp_path: Path) -> None:
    external = tmp_path / "external.bin"
    external.write_bytes(b"before")
    root = tmp_path / "root"
    root.mkdir()
    (root / "link.bin").symlink_to(external)

    accountant = _accountant()
    before, _remaining = accountant.capture(root, 100)
    external.write_bytes(b"after!")
    after, _remaining = accountant.capture(root, 100)

    assert before == after
    assert before["regular_files"] == 0
    assert before["symlinks"] == 1


def test_snapshot_rejects_regular_file_over_hash_limit(tmp_path: Path) -> None:
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"four")

    with pytest.raises(ValidationError) as captured:
        _accountant(max_file_bytes=3).capture(payload, 100)

    assert captured.value.code == "ARTIFACT_RETENTION_FILE_LIMIT_EXCEEDED"


def test_snapshot_rejects_path_replacement_during_hashing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"before")
    original_read = artifact_retention_accounting.os.read
    replaced = False

    def replacing_read(descriptor: int, size: int) -> bytes:
        nonlocal replaced
        chunk = original_read(descriptor, size)
        if not replaced:
            replacement = tmp_path / "replacement.bin"
            replacement.write_bytes(b"after!")
            os.replace(replacement, payload)
            replaced = True
        return chunk

    monkeypatch.setattr(artifact_retention_accounting.os, "read", replacing_read)

    with pytest.raises(ValidationError) as captured:
        _accountant().capture(payload, 100)

    assert captured.value.code == "ARTIFACT_RETENTION_ENTRY_CHANGED"
