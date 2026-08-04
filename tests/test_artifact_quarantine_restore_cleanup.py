from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import pytest

from weave_frontend.artifact_quarantine import ArtifactQuarantineService
from weave_frontend.artifact_quarantine_restore import (
    ArtifactQuarantineRestoreService,
)
from weave_frontend.artifact_reachability import ArtifactReconciliationService
from weave_frontend.artifact_reconciliation import (
    RetainedArtifactFamily,
    RetainedArtifactInventoryService,
)
from weave_frontend.artifact_retention import (
    ARTIFACT_RETENTION_POLICY_FORMAT,
    ArtifactRetentionPlanner,
)
from weave_frontend.database import Database

_HEX32 = re.compile(r"^[0-9a-f]{32}$")


def test_restore_resumes_partially_completed_capsule_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = Database(tmp_path / "jacquard.db")
    database.initialize_project("demo")
    root = tmp_path / "builds"
    root.mkdir()
    artifact_id = "f" * 32
    source = root / artifact_id
    source.mkdir()
    (source / "payload.bin").write_bytes(b"cleanup")
    os.utime(source, ns=(1, 1))
    evidence: dict[str, dict[str, Any]] = {
        artifact_id: {
            "build_id": artifact_id,
            "project": "removed",
            "revision_id": "missing",
            "manifest_sha256": "f" * 64,
        }
    }
    inventory = RetainedArtifactInventoryService(
        [
            RetainedArtifactFamily(
                "committed_builds",
                root,
                _HEX32,
                lambda value: evidence[value],
            )
        ]
    )
    reconciliation = ArtifactReconciliationService(database, inventory)
    policy = {
        "format": ARTIFACT_RETENTION_POLICY_FORMAT,
        "reconciliation_id": reconciliation.report()["reconciliation_id"],
        "rules": [
            {
                "family": "committed_builds",
                "classification": "orphaned",
                "minimum_age_seconds": 0,
                "minimum_retained_count": 0,
                "protected_artifact_ids": [],
            }
        ],
    }
    plan = ArtifactRetentionPlanner(reconciliation).plan(
        policy,
        as_of_unix_ns=10_000_000_000,
    )
    quarantine = ArtifactQuarantineService(reconciliation).quarantine(
        policy,
        plan,
        entry_id=plan["entries"][0]["entry_id"],
        quarantined_at_unix_ns=20,
    )
    service = ArtifactQuarantineRestoreService(reconciliation)
    original_unlink = Path.unlink
    interrupted = False

    def interrupt_manifest(path: Path, *args: Any, **kwargs: Any) -> None:
        nonlocal interrupted
        if path.name == "quarantine-manifest.json" and not interrupted:
            interrupted = True
            raise RuntimeError("simulated cleanup interruption")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", interrupt_manifest)
    try:
        with pytest.raises(RuntimeError, match="simulated cleanup interruption"):
            service.restore(
                quarantine_id=quarantine["quarantine_id"],
                manifest_id=quarantine["manifest_id"],
                restored_at_unix_ns=30,
            )
        capsule = root / f".quarantine-{quarantine['quarantine_entry_id']}"
        assert (root / artifact_id).is_dir()
        assert sorted(path.name for path in capsule.iterdir()) == [
            "quarantine-manifest.json"
        ]

        monkeypatch.setattr(Path, "unlink", original_unlink)
        result = service.restore(
            quarantine_id=quarantine["quarantine_id"],
            manifest_id=quarantine["manifest_id"],
            restored_at_unix_ns=40,
        )
        assert result["complete"] is True
        assert result["restored_at_unix_ns"] == 30
        assert not os.path.lexists(capsule)
    finally:
        database.close()
