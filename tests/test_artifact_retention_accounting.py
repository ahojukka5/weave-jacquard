from __future__ import annotations

import os
from pathlib import Path

from weave_frontend.artifact_reconciliation import (
    RetainedArtifactInventoryService,
)
from weave_frontend.artifact_retention_accounting import (
    ArtifactRetentionAccountant,
)


def test_relocation_snapshot_survives_rename_and_detects_payload_change(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    payload = source / "payload.bin"
    payload.write_bytes(b"before")

    accountant = ArtifactRetentionAccountant(
        RetainedArtifactInventoryService.__new__(
            RetainedArtifactInventoryService
        ),
        max_scan_entries=100,
    )
    before, _remaining = accountant.capture(source, 100)
    destination = tmp_path / "destination"
    os.replace(source, destination)
    moved, _remaining = accountant.capture(destination, 100)

    assert moved["relocation_snapshot_id"] == before["relocation_snapshot_id"]
    assert moved["logical_bytes"] == before["logical_bytes"]

    (destination / "payload.bin").write_bytes(b"after-longer")
    changed, _remaining = accountant.capture(destination, 100)
    assert changed["relocation_snapshot_id"] != before["relocation_snapshot_id"]
