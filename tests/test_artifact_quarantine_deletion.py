from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import pytest

from weave_frontend.artifacts.quarantine.deletion import (
    ArtifactQuarantineDeleteService,
)
from weave_frontend.artifacts.quarantine.deletion_batch import (
    ArtifactQuarantineDeleteBatchService,
)
from weave_frontend.artifacts.quarantine.service import ArtifactQuarantineService
from weave_frontend.artifacts.quarantine.verification import (
    ArtifactQuarantineVerificationService,
)
from weave_frontend.artifacts.reconciliation import (
    ArtifactReconciliationService,
    RetainedArtifactFamily,
    RetainedArtifactInventoryService,
)
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
) -> None:
    path = root / artifact_id
    path.mkdir()
    (path / "payload.bin").write_bytes(payload)
    os.utime(path, ns=(1, 1))
    evidence[artifact_id] = {
        "build_id": artifact_id,
        "project": "removed",
        "revision_id": "missing",
        "manifest_sha256": artifact_id[0] * 64,
    }


def _plan(
    reconciliation: ArtifactReconciliationService,
    *,
    classification: str = "orphaned",
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
    plan = ArtifactRetentionPlanner(reconciliation).plan(
        policy,
        as_of_unix_ns=10 * _SECOND,
    )
    return policy, plan


def _quarantine(
    reconciliation: ArtifactReconciliationService,
    policy: dict[str, Any],
    plan: dict[str, Any],
    *,
    entry_index: int = 0,
) -> dict[str, Any]:
    return ArtifactQuarantineService(reconciliation).quarantine(
        policy,
        plan,
        entry_id=plan["entries"][entry_index]["entry_id"],
        quarantined_at_unix_ns=20,
    )


def _verification(
    reconciliation: ArtifactReconciliationService,
    quarantine: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    return ArtifactQuarantineVerificationService(reconciliation).verify(
        quarantine_id=quarantine["quarantine_id"],
        manifest_id=quarantine["manifest_id"],
        plan_id=plan["plan_id"],
        minimum_holding_seconds=1,
        as_of_unix_ns=2 * _SECOND,
    )


def _delete_arguments(
    quarantine: dict[str, Any],
    plan: dict[str, Any],
    verification: dict[str, Any],
) -> dict[str, Any]:
    return {
        "quarantine_id": quarantine["quarantine_id"],
        "manifest_id": quarantine["manifest_id"],
        "plan_id": plan["plan_id"],
        "verification_id": verification["verification_id"],
        "minimum_holding_seconds": 1,
        "as_of_unix_ns": 2 * _SECOND,
    }


def test_verification_enforces_holding_period_and_is_deterministic(
    tmp_path: Path,
) -> None:
    database, root, evidence, reconciliation = _fixture(tmp_path)
    artifact_id = "a" * 32
    _add_orphan(root, evidence, artifact_id, payload=b"payload")
    policy, plan = _plan(reconciliation)
    quarantine = _quarantine(reconciliation, policy, plan)
    service = ArtifactQuarantineVerificationService(reconciliation)
    try:
        with pytest.raises(ValidationError) as captured:
            service.verify(
                quarantine_id=quarantine["quarantine_id"],
                manifest_id=quarantine["manifest_id"],
                plan_id=plan["plan_id"],
                minimum_holding_seconds=1,
                as_of_unix_ns=100,
            )
        assert captured.value.code == ("ARTIFACT_QUARANTINE_HOLDING_PERIOD_NOT_MET")

        first = _verification(reconciliation, quarantine, plan)
        second = _verification(reconciliation, quarantine, plan)
    finally:
        database.close()

    assert first == second
    assert first["complete"] is True
    assert first["mutation"] == "none"
    assert first["deletion_eligible"] is True
    assert first["artifact_id"] == artifact_id
    assert first["payload"]["logical_bytes"] == len(b"payload")
    assert str(tmp_path) not in str(first)


def test_delete_is_exact_permanent_and_idempotent(tmp_path: Path) -> None:
    database, root, evidence, reconciliation = _fixture(tmp_path)
    artifact_id = "b" * 32
    _add_orphan(root, evidence, artifact_id, payload=b"payload")
    policy, plan = _plan(reconciliation)
    quarantine = _quarantine(reconciliation, policy, plan)
    verification = _verification(reconciliation, quarantine, plan)
    arguments = _delete_arguments(quarantine, plan, verification)
    service = ArtifactQuarantineDeleteService(reconciliation)
    try:
        first = service.delete(**arguments, deleted_at_unix_ns=3 * _SECOND)
        second = service.delete(**arguments, deleted_at_unix_ns=9 * _SECOND)
        report = reconciliation.report()
    finally:
        database.close()

    assert first == second
    assert first["complete"] is True
    assert first["mutation"] == "delete"
    assert first["deletion"] == "permanent"
    assert first["restorable"] is False
    assert first["logical_bytes_reclaimed"] == len(b"payload")
    assert not os.path.lexists(root / artifact_id)
    assert not os.path.lexists(root / f".quarantine-{quarantine['quarantine_entry_id']}")
    assert report["aggregate"]["counts"]["quarantined"] == 0
    assert str(tmp_path) not in str(first)


def test_delete_rejects_wrong_exact_plan_identity(tmp_path: Path) -> None:
    database, root, evidence, reconciliation = _fixture(tmp_path)
    _add_orphan(root, evidence, "c" * 32, payload=b"payload")
    policy, plan = _plan(reconciliation)
    quarantine = _quarantine(reconciliation, policy, plan)
    verification = _verification(reconciliation, quarantine, plan)
    try:
        with pytest.raises(ValidationError) as captured:
            ArtifactQuarantineDeleteService(reconciliation).delete(
                quarantine_id=quarantine["quarantine_id"],
                manifest_id=quarantine["manifest_id"],
                plan_id="f" * 64,
                verification_id=verification["verification_id"],
                minimum_holding_seconds=1,
                as_of_unix_ns=2 * _SECOND,
            )
        assert captured.value.code == "ARTIFACT_QUARANTINE_PLAN_ID_MISMATCH"
        assert (root / f".quarantine-{quarantine['quarantine_entry_id']}").is_dir()
    finally:
        database.close()


def test_delete_resumes_after_capsule_removal_before_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, root, evidence, reconciliation = _fixture(tmp_path)
    artifact_id = "d" * 32
    _add_orphan(root, evidence, artifact_id, payload=b"resume")
    policy, plan = _plan(reconciliation)
    quarantine = _quarantine(reconciliation, policy, plan)
    verification = _verification(reconciliation, quarantine, plan)
    arguments = _delete_arguments(quarantine, plan, verification)
    service = ArtifactQuarantineDeleteService(reconciliation)
    original_write = service.io.write_metadata
    interrupted = False

    def interrupt_result(path: Path, value: Any) -> None:
        nonlocal interrupted
        if path.name.endswith(".delete-result.json") and not interrupted:
            interrupted = True
            raise RuntimeError("simulated delete interruption")
        original_write(path, value)

    monkeypatch.setattr(service.io, "write_metadata", interrupt_result)
    try:
        with pytest.raises(RuntimeError, match="simulated delete interruption"):
            service.delete(**arguments, deleted_at_unix_ns=4 * _SECOND)
        assert not os.path.lexists(root / f".quarantine-{quarantine['quarantine_entry_id']}")

        monkeypatch.setattr(service.io, "write_metadata", original_write)
        result = service.delete(**arguments, deleted_at_unix_ns=8 * _SECOND)
        assert result["complete"] is True
        assert result["deleted_at_unix_ns"] == 4 * _SECOND
    finally:
        database.close()


def test_delete_does_not_follow_quarantined_symlink_target(tmp_path: Path) -> None:
    database, root, _evidence, reconciliation = _fixture(tmp_path)
    external = tmp_path / "outside.bin"
    external.write_bytes(b"outside")
    source = root / "unrelated-link"
    source.symlink_to(external)
    os.utime(source, ns=(1, 1), follow_symlinks=False)
    policy, plan = _plan(reconciliation, classification="unknown")
    quarantine = _quarantine(reconciliation, policy, plan)
    verification = _verification(reconciliation, quarantine, plan)
    try:
        result = ArtifactQuarantineDeleteService(reconciliation).delete(
            **_delete_arguments(quarantine, plan, verification),
            deleted_at_unix_ns=5 * _SECOND,
        )
    finally:
        database.close()

    assert result["payload_entries_deleted"] == 1
    assert external.read_bytes() == b"outside"
    assert not os.path.lexists(source)


def _prepare_two_quarantines(
    reconciliation: ArtifactReconciliationService,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    first_policy, first_plan = _plan(reconciliation)
    first_quarantine = _quarantine(
        reconciliation,
        first_policy,
        first_plan,
        entry_index=0,
    )
    second_policy, second_plan = _plan(reconciliation)
    second_quarantine = _quarantine(
        reconciliation,
        second_policy,
        second_plan,
        entry_index=0,
    )
    return first_plan, first_quarantine, second_plan, second_quarantine


def test_delete_batch_completes_multiple_exact_entries(tmp_path: Path) -> None:
    database, root, evidence, reconciliation = _fixture(tmp_path)
    _add_orphan(root, evidence, "e" * 32, payload=b"first")
    _add_orphan(root, evidence, "f" * 32, payload=b"second")
    first_plan, first_quarantine, second_plan, second_quarantine = _prepare_two_quarantines(
        reconciliation
    )
    first_verification = _verification(
        reconciliation,
        first_quarantine,
        first_plan,
    )
    second_verification = _verification(
        reconciliation,
        second_quarantine,
        second_plan,
    )
    entries = [
        _delete_arguments(first_quarantine, first_plan, first_verification),
        _delete_arguments(second_quarantine, second_plan, second_verification),
    ]
    try:
        result = ArtifactQuarantineDeleteBatchService(reconciliation).delete_batch(entries)
    finally:
        database.close()

    assert result["complete"] is True
    assert result["requested"] == 2
    assert result["succeeded"] == 2
    assert result["failed"] == 0
    assert all(item["ok"] is True for item in result["outcomes"])


def test_delete_batch_reports_partial_failure_and_replays_success(
    tmp_path: Path,
) -> None:
    database, root, evidence, reconciliation = _fixture(tmp_path)
    _add_orphan(root, evidence, "1" * 32, payload=b"first")
    _add_orphan(root, evidence, "2" * 32, payload=b"second")
    first_plan, first_quarantine, second_plan, second_quarantine = _prepare_two_quarantines(
        reconciliation
    )
    first_verification = _verification(
        reconciliation,
        first_quarantine,
        first_plan,
    )
    second_verification = _verification(
        reconciliation,
        second_quarantine,
        second_plan,
    )
    entries = [
        _delete_arguments(first_quarantine, first_plan, first_verification),
        {
            **_delete_arguments(
                second_quarantine,
                second_plan,
                second_verification,
            ),
            "verification_id": "0" * 64,
        },
    ]
    service = ArtifactQuarantineDeleteBatchService(reconciliation)
    try:
        first = service.delete_batch(entries)
        second = service.delete_batch(entries)
    finally:
        database.close()

    assert first["complete"] is False
    assert first["requested"] == 2
    assert first["succeeded"] == 1
    assert first["failed"] == 1
    assert first["outcomes"][0]["ok"] is True
    assert first["outcomes"][1]["ok"] is False
    assert first["outcomes"][1]["error"]["code"] == (
        "ARTIFACT_QUARANTINE_DELETE_VERIFICATION_MISMATCH"
    )
    assert second == first
    assert not os.path.lexists(root / f".quarantine-{first_quarantine['quarantine_entry_id']}")
    assert (root / f".quarantine-{second_quarantine['quarantine_entry_id']}").is_dir()
