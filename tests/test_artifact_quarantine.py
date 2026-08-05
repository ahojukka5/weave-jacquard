from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

import weave_frontend.artifact_quarantine as quarantine_module
from weave_frontend.artifact_quarantine import ArtifactQuarantineService
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
    str,
]:
    database = Database(tmp_path / "jacquard.db")
    _project_id, revision_id = database.initialize_project("demo")
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
        revision_id,
    )


def _add_build(
    root: Path,
    evidence: dict[str, dict[str, Any]],
    artifact_id: str,
    *,
    project: str,
    revision_id: str,
    mtime_ns: int,
    payload: bytes,
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
        "project": project,
        "revision_id": revision_id,
        "manifest_sha256": artifact_id[0] * 64,
    }
    return path


def _plan(
    reconciliation: ArtifactReconciliationService,
    *,
    classification: str,
    as_of: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    reconciliation_id = reconciliation.report()["reconciliation_id"]
    policy = {
        "format": ARTIFACT_RETENTION_POLICY_FORMAT,
        "reconciliation_id": reconciliation_id,
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
            as_of_unix_ns=as_of,
        ),
    )


def test_quarantine_is_verified_path_redacted_and_idempotent(
    tmp_path: Path,
) -> None:
    database, root, evidence, reconciliation, _revision_id = _fixture(tmp_path)
    artifact_id = "a" * 32
    as_of = 10_000 * _SECOND
    external = tmp_path / "external-secret.bin"
    external.write_bytes(b"x" * 4096)
    _add_build(
        root,
        evidence,
        artifact_id,
        project="removed",
        revision_id="missing",
        mtime_ns=as_of - 1_000 * _SECOND,
        payload=b"payload",
        symlink_target=external,
    )
    policy, plan = _plan(
        reconciliation,
        classification="orphaned",
        as_of=as_of,
    )
    entry = plan["entries"][0]
    service = ArtifactQuarantineService(reconciliation)
    try:
        first = service.quarantine(
            policy,
            plan,
            entry_id=entry["entry_id"],
            quarantined_at_unix_ns=12_345,
        )
        second = service.quarantine(
            policy,
            plan,
            entry_id=entry["entry_id"],
            quarantined_at_unix_ns=99_999,
        )
        report = reconciliation.report()
    finally:
        database.close()

    assert first == second
    assert first["complete"] is True
    assert first["mutation"] == "quarantine"
    assert first["deletion"] == "none"
    assert first["restorable"] is True
    assert first["artifact_id"] == artifact_id
    assert first["quarantined_at_unix_ns"] == 12_345
    assert first["payload"]["logical_bytes"] == len(b"payload")
    assert first["payload"]["symlinks"] == 1
    assert not os.path.lexists(root / artifact_id)

    capsule = root / f".quarantine-{first['quarantine_entry_id']}"
    assert capsule.is_dir()
    assert sorted(path.name for path in capsule.iterdir()) == [
        "payload",
        "quarantine-intent.json",
        "quarantine-manifest.json",
    ]
    assert (capsule / "payload" / "external-link").is_symlink()
    assert external.read_bytes() == b"x" * 4096
    assert (root / f".{artifact_id}.lock").is_file()
    assert report["aggregate"]["counts"]["quarantined"] == 1

    rendered = json.dumps(first, sort_keys=True)
    assert str(tmp_path) not in rendered
    assert str(external) not in rendered


def test_quarantine_rejects_source_changed_after_plan(tmp_path: Path) -> None:
    database, root, evidence, reconciliation, _revision_id = _fixture(tmp_path)
    artifact_id = "b" * 32
    source = _add_build(
        root,
        evidence,
        artifact_id,
        project="removed",
        revision_id="missing",
        mtime_ns=1,
        payload=b"before",
    )
    policy, plan = _plan(
        reconciliation,
        classification="orphaned",
        as_of=10 * _SECOND,
    )
    (source / "payload.bin").write_bytes(b"after!")
    try:
        with pytest.raises(ValidationError) as captured:
            ArtifactQuarantineService(reconciliation).quarantine(
                policy,
                plan,
                entry_id=plan["entries"][0]["entry_id"],
                quarantined_at_unix_ns=20,
            )
        assert captured.value.code == "ARTIFACT_QUARANTINE_STALE_PLAN"
        assert source.is_dir()
    finally:
        database.close()


def test_quarantine_resumes_after_move_interruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, root, evidence, reconciliation, _revision_id = _fixture(tmp_path)
    artifact_id = "c" * 32
    _add_build(
        root,
        evidence,
        artifact_id,
        project="removed",
        revision_id="missing",
        mtime_ns=1,
        payload=b"resume",
    )
    policy, plan = _plan(
        reconciliation,
        classification="orphaned",
        as_of=10 * _SECOND,
    )
    entry_id = plan["entries"][0]["entry_id"]
    service = ArtifactQuarantineService(reconciliation)
    original_replace = quarantine_module.os.replace
    interrupted = False

    def replace_then_interrupt(source: Any, destination: Any) -> None:
        nonlocal interrupted
        original_replace(source, destination)
        if Path(destination).name == "payload" and not interrupted:
            interrupted = True
            raise RuntimeError("simulated interruption")

    monkeypatch.setattr(quarantine_module.os, "replace", replace_then_interrupt)
    try:
        with pytest.raises(RuntimeError, match="simulated interruption"):
            service.quarantine(
                policy,
                plan,
                entry_id=entry_id,
                quarantined_at_unix_ns=30,
            )
        assert not os.path.lexists(root / artifact_id)
        assert any(
            path.name.startswith(".quarantine-") and path.name.endswith(".staging")
            for path in root.iterdir()
        )

        monkeypatch.setattr(quarantine_module.os, "replace", original_replace)
        result = service.quarantine(
            policy,
            plan,
            entry_id=entry_id,
            quarantined_at_unix_ns=40,
        )
        assert result["complete"] is True
        assert result["quarantined_at_unix_ns"] == 30
        assert not any(path.name.endswith(".staging") for path in root.iterdir())
    finally:
        database.close()


def test_quarantine_retry_rejects_unrelated_root_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, root, evidence, reconciliation, _revision_id = _fixture(tmp_path)
    artifact_id = "d" * 32
    _add_build(
        root,
        evidence,
        artifact_id,
        project="removed",
        revision_id="missing",
        mtime_ns=1,
        payload=b"resume",
    )
    policy, plan = _plan(
        reconciliation,
        classification="orphaned",
        as_of=10 * _SECOND,
    )
    entry_id = plan["entries"][0]["entry_id"]
    service = ArtifactQuarantineService(reconciliation)
    original_replace = quarantine_module.os.replace

    def replace_then_interrupt(source: Any, destination: Any) -> None:
        original_replace(source, destination)
        if Path(destination).name == "payload":
            raise RuntimeError("simulated interruption")

    monkeypatch.setattr(quarantine_module.os, "replace", replace_then_interrupt)
    try:
        with pytest.raises(RuntimeError):
            service.quarantine(
                policy,
                plan,
                entry_id=entry_id,
                quarantined_at_unix_ns=50,
            )
        monkeypatch.setattr(quarantine_module.os, "replace", original_replace)
        (root / "unrelated-entry").mkdir()
        with pytest.raises(ValidationError) as captured:
            service.quarantine(
                policy,
                plan,
                entry_id=entry_id,
                quarantined_at_unix_ns=60,
            )
        assert captured.value.code == "ARTIFACT_QUARANTINE_STALE_PLAN"
    finally:
        database.close()


def test_quarantine_moves_unknown_symlink_without_following_target(
    tmp_path: Path,
) -> None:
    database, root, _evidence, reconciliation, _revision_id = _fixture(tmp_path)
    external = tmp_path / "outside.bin"
    external.write_bytes(b"outside")
    source = root / "unrelated-link"
    source.symlink_to(external)
    os.utime(source, ns=(1, 1), follow_symlinks=False)
    policy, plan = _plan(
        reconciliation,
        classification="unknown",
        as_of=10 * _SECOND,
    )
    entry = next(item for item in plan["entries"] if item["entry_type"] == "symlink")
    try:
        result = ArtifactQuarantineService(reconciliation).quarantine(
            policy,
            plan,
            entry_id=entry["entry_id"],
            quarantined_at_unix_ns=70,
        )
    finally:
        database.close()

    assert not os.path.lexists(source)
    capsule = root / f".quarantine-{result['quarantine_entry_id']}"
    assert (capsule / "payload").is_symlink()
    assert result["payload"]["symlinks"] == 1
    assert result["payload"]["logical_bytes"] == 0
    assert external.read_bytes() == b"outside"


def test_quarantine_detects_publication_race_after_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, root, evidence, reconciliation, _revision_id = _fixture(tmp_path)
    artifact_id = "e" * 32
    source = _add_build(
        root,
        evidence,
        artifact_id,
        project="removed",
        revision_id="missing",
        mtime_ns=1,
        payload=b"before",
    )
    policy, plan = _plan(
        reconciliation,
        classification="orphaned",
        as_of=10 * _SECOND,
    )
    service = ArtifactQuarantineService(reconciliation)
    original_write = service.io.write_metadata
    changed = False

    def write_then_change(path: Path, value: Any) -> None:
        nonlocal changed
        original_write(path, value)
        if path.parent == service.io.control_root and not changed:
            changed = True
            (source / "payload.bin").write_bytes(b"after!")

    monkeypatch.setattr(service.io, "write_metadata", write_then_change)
    try:
        with pytest.raises(ValidationError) as captured:
            service.quarantine(
                policy,
                plan,
                entry_id=plan["entries"][0]["entry_id"],
                quarantined_at_unix_ns=80,
            )
        assert captured.value.code == "ARTIFACT_QUARANTINE_SOURCE_CHANGED"
        assert source.is_dir()
    finally:
        database.close()
