from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import pytest

from weave_frontend.artifact_reachability import ArtifactReconciliationService
from weave_frontend.artifact_reconciliation import (
    RetainedArtifactFamily,
    RetainedArtifactInventoryService,
)
from weave_frontend.artifacts.quarantine.restoration import (
    ArtifactQuarantineRestoreService,
)
from weave_frontend.artifacts.quarantine.service import ArtifactQuarantineService
from weave_frontend.artifacts.retention import (
    ARTIFACT_RETENTION_POLICY_FORMAT,
    ArtifactRetentionPlanner,
)
from weave_frontend.database import Database
from weave_frontend.errors import ValidationError

_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_SECOND = 1_000_000_000


def _fixture(
    tmp_path: Path,
) -> tuple[
    Database,
    Path,
    dict[str, dict[str, Any]],
    ArtifactReconciliationService,
]:
    database = Database(tmp_path / "jacquard.db")
    database.initialize_project("demo")
    root = tmp_path / "builds"
    root.mkdir()
    evidence: dict[str, dict[str, Any]] = {}

    def verify(artifact_id: str) -> dict[str, Any]:
        return evidence[artifact_id]

    inventory = RetainedArtifactInventoryService(
        [
            RetainedArtifactFamily(
                "committed_builds",
                root,
                _HEX32,
                verify,
            )
        ]
    )
    return (
        database,
        root,
        evidence,
        ArtifactReconciliationService(database, inventory),
    )


def _add_orphan(
    root: Path,
    evidence: dict[str, dict[str, Any]],
    artifact_id: str,
    *,
    payload: bytes,
    mtime_ns: int = 1,
    symlink_target: Path | None = None,
) -> Path:
    path = root / artifact_id
    path.mkdir()
    (path / "payload.bin").write_bytes(payload)
    if symlink_target is not None:
        (path / "external-link").symlink_to(symlink_target)
    os.utime(path, ns=(mtime_ns, mtime_ns))
    evidence[artifact_id] = {
        "build_id": artifact_id,
        "project": "removed",
        "revision_id": "missing",
        "manifest_sha256": artifact_id[0] * 64,
    }
    return path


def _plan(
    reconciliation: ArtifactReconciliationService,
    *,
    classification: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    policy = {
        "format": ARTIFACT_RETENTION_POLICY_FORMAT,
        "reconciliation_id": reconciliation.report()["reconciliation_id"],
        "rules": [
            {
                "family": "committed_builds",
                "classification": classification,
                "minimum_age_seconds": 0,
                "minimum_retained_count": 0,
                "protected_artifact_ids": [],
            }
        ],
    }
    return (
        policy,
        ArtifactRetentionPlanner(reconciliation).plan(
            policy,
            as_of_unix_ns=10 * _SECOND,
        ),
    )


def _quarantine(
    reconciliation: ArtifactReconciliationService,
    policy: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    return ArtifactQuarantineService(reconciliation).quarantine(
        policy,
        plan,
        entry_id=plan["entries"][0]["entry_id"],
        quarantined_at_unix_ns=20,
    )


def test_restore_is_verified_path_redacted_and_idempotent(tmp_path: Path) -> None:
    database, root, evidence, reconciliation = _fixture(tmp_path)
    artifact_id = "a" * 32
    external = tmp_path / "external.bin"
    external.write_bytes(b"outside")
    _add_orphan(
        root,
        evidence,
        artifact_id,
        payload=b"payload",
        symlink_target=external,
    )
    policy, plan = _plan(reconciliation, classification="orphaned")
    quarantine = _quarantine(reconciliation, policy, plan)
    service = ArtifactQuarantineRestoreService(reconciliation)
    try:
        first = service.restore(
            quarantine_id=quarantine["quarantine_id"],
            manifest_id=quarantine["manifest_id"],
            restored_at_unix_ns=30,
        )
        second = service.restore(
            quarantine_id=quarantine["quarantine_id"],
            manifest_id=quarantine["manifest_id"],
            restored_at_unix_ns=99,
        )
        report = reconciliation.report()
    finally:
        database.close()

    assert first == second
    assert first["complete"] is True
    assert first["mutation"] == "restore"
    assert first["deletion"] == "quarantine-metadata-only"
    assert first["restored_at_unix_ns"] == 30
    assert first["artifact_id"] == artifact_id
    assert first["payload"]["logical_bytes"] == len(b"payload")
    restored = root / artifact_id
    assert restored.is_dir()
    assert (restored / "payload.bin").read_bytes() == b"payload"
    assert (restored / "external-link").is_symlink()
    assert external.read_bytes() == b"outside"
    assert not os.path.lexists(root / f".quarantine-{quarantine['quarantine_entry_id']}")
    assert report["aggregate"]["counts"]["orphaned"] == 1
    assert report["aggregate"]["counts"]["quarantined"] == 0
    assert str(tmp_path) not in str(first)


def test_restore_rejects_live_destination_conflict(tmp_path: Path) -> None:
    database, root, evidence, reconciliation = _fixture(tmp_path)
    artifact_id = "b" * 32
    _add_orphan(root, evidence, artifact_id, payload=b"payload")
    policy, plan = _plan(reconciliation, classification="orphaned")
    quarantine = _quarantine(reconciliation, policy, plan)
    conflict = root / artifact_id
    conflict.mkdir()
    try:
        with pytest.raises(ValidationError) as captured:
            ArtifactQuarantineRestoreService(reconciliation).restore(
                quarantine_id=quarantine["quarantine_id"],
                manifest_id=quarantine["manifest_id"],
                restored_at_unix_ns=40,
            )
        assert captured.value.code == ("ARTIFACT_QUARANTINE_RESTORE_DESTINATION_EXISTS")
        assert conflict.is_dir()
        assert (root / f".quarantine-{quarantine['quarantine_entry_id']}").is_dir()
    finally:
        database.close()


def test_restore_rejects_changed_quarantined_payload(tmp_path: Path) -> None:
    database, root, evidence, reconciliation = _fixture(tmp_path)
    artifact_id = "c" * 32
    _add_orphan(root, evidence, artifact_id, payload=b"before")
    policy, plan = _plan(reconciliation, classification="orphaned")
    quarantine = _quarantine(reconciliation, policy, plan)
    capsule = root / f".quarantine-{quarantine['quarantine_entry_id']}"
    (capsule / "payload" / "payload.bin").write_bytes(b"after!")
    try:
        with pytest.raises(ValidationError) as captured:
            ArtifactQuarantineRestoreService(reconciliation).restore(
                quarantine_id=quarantine["quarantine_id"],
                manifest_id=quarantine["manifest_id"],
                restored_at_unix_ns=50,
            )
        assert captured.value.code == ("ARTIFACT_QUARANTINE_RESTORE_METADATA_INVALID")
        assert not os.path.lexists(root / artifact_id)
        assert capsule.is_dir()
    finally:
        database.close()


def test_restore_resumes_after_payload_move(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, root, evidence, reconciliation = _fixture(tmp_path)
    artifact_id = "d" * 32
    _add_orphan(root, evidence, artifact_id, payload=b"resume")
    policy, plan = _plan(reconciliation, classification="orphaned")
    quarantine = _quarantine(reconciliation, policy, plan)
    service = ArtifactQuarantineRestoreService(reconciliation)
    original_write = service.io.write_metadata
    interrupted = False

    def interrupt_result(path: Path, value: Any) -> None:
        nonlocal interrupted
        if path.name.endswith(".restore-result.json") and not interrupted:
            interrupted = True
            raise RuntimeError("simulated restore interruption")
        original_write(path, value)

    monkeypatch.setattr(service.io, "write_metadata", interrupt_result)
    try:
        with pytest.raises(RuntimeError, match="simulated restore interruption"):
            service.restore(
                quarantine_id=quarantine["quarantine_id"],
                manifest_id=quarantine["manifest_id"],
                restored_at_unix_ns=60,
            )
        assert (root / artifact_id).is_dir()
        capsule = root / f".quarantine-{quarantine['quarantine_entry_id']}"
        assert sorted(path.name for path in capsule.iterdir()) == [
            "quarantine-intent.json",
            "quarantine-manifest.json",
        ]

        monkeypatch.setattr(service.io, "write_metadata", original_write)
        result = service.restore(
            quarantine_id=quarantine["quarantine_id"],
            manifest_id=quarantine["manifest_id"],
            restored_at_unix_ns=70,
        )
        assert result["complete"] is True
        assert result["restored_at_unix_ns"] == 60
        assert not os.path.lexists(capsule)
    finally:
        database.close()


def test_restore_preserves_top_level_symlink_without_following_target(
    tmp_path: Path,
) -> None:
    database, root, _evidence, reconciliation = _fixture(tmp_path)
    external = tmp_path / "outside.bin"
    external.write_bytes(b"outside")
    source = root / "unrelated-link"
    source.symlink_to(external)
    os.utime(source, ns=(1, 1), follow_symlinks=False)
    policy, plan = _plan(reconciliation, classification="unknown")
    quarantine = _quarantine(reconciliation, policy, plan)
    try:
        result = ArtifactQuarantineRestoreService(reconciliation).restore(
            quarantine_id=quarantine["quarantine_id"],
            manifest_id=quarantine["manifest_id"],
            restored_at_unix_ns=80,
        )
    finally:
        database.close()

    assert source.is_symlink()
    assert source.readlink() == external
    assert external.read_bytes() == b"outside"
    assert result["payload"]["symlinks"] == 1
    assert result["payload"]["logical_bytes"] == 0
