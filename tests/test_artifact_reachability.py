from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest

from weave_frontend.artifacts.reconciliation import (
    ARTIFACT_RECONCILIATION_FORMAT,
    RETAINED_ARTIFACT_FAMILIES,
    ArtifactReconciliationService,
    RetainedArtifactFamily,
    RetainedArtifactInventoryService,
)
from weave_frontend.database import Database
from weave_frontend.errors import ValidationError

_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _location_id(path: Path) -> str:
    return hashlib.sha256(
        b"weave-database-location-v1\0" + str(path.resolve()).encode("utf-8")
    ).hexdigest()


def _subject(project: str, revision_id: str) -> dict[str, Any]:
    return {
        "kind": "virtual_merge_candidate",
        "project": project,
        "target_branch": "main",
        "source_branch": "feature",
        "base_revision_id": revision_id,
        "target_head_revision_id": revision_id,
        "source_head_revision_id": revision_id,
        "preview_id": "f" * 64,
        "merged_root_hash": "e" * 64,
        "committed_revision_id": None,
    }


def _families(
    tmp_path: Path,
    evidence: dict[str, dict[str, dict[str, Any]]],
) -> tuple[RetainedArtifactFamily, ...]:
    families: list[RetainedArtifactFamily] = []
    for family in RETAINED_ARTIFACT_FAMILIES:
        root = tmp_path / family
        root.mkdir()
        values = evidence.get(family, {})
        for artifact_id in values:
            (root / artifact_id).mkdir()

        def verify(
            artifact_id: str,
            *,
            values: dict[str, dict[str, Any]] = values,
        ) -> dict[str, Any]:
            return values[artifact_id]

        pattern = _HEX64 if family == "database_backups" else _HEX32
        families.append(RetainedArtifactFamily(family, root, pattern, verify))
    return tuple(families)


def _database(tmp_path: Path) -> tuple[Database, str]:
    database = Database(tmp_path / "jacquard.db")
    _project_id, revision_id = database.initialize_project("demo")
    return database, revision_id


def test_reconciliation_classifies_reachable_orphaned_and_missing_evidence(
    tmp_path: Path,
) -> None:
    database, revision_id = _database(tmp_path)
    build_id = "a" * 32
    run_id = "b" * 32
    batch_id = "c" * 32
    missing_run_id = "d" * 32
    candidate_id = "1" * 32
    orphan_candidate_id = "2" * 32
    qualification_id = "3" * 32
    attestation_id = "4" * 32
    backup_id = "5" * 64
    orphan_backup_id = "6" * 64
    evidence = {
        "committed_builds": {
            build_id: {
                "build_id": build_id,
                "project": "demo",
                "revision_id": revision_id,
                "manifest_sha256": "a" * 64,
            }
        },
        "test_runs": {
            run_id: {
                "run_id": run_id,
                "project": "demo",
                "revision_id": revision_id,
                "build_id": build_id,
                "manifest_sha256": "b" * 64,
            }
        },
        "test_batches": {
            batch_id: {
                "batch_id": batch_id,
                "project": "demo",
                "revision_id": revision_id,
                "results": [
                    {"run_id": run_id},
                    {"run_id": missing_run_id},
                ],
                "manifest_sha256": "c" * 64,
            }
        },
        "candidate_builds": {
            candidate_id: {
                "build_id": candidate_id,
                "subject": _subject("demo", revision_id),
                "manifest_sha256": "d" * 64,
            },
            orphan_candidate_id: {
                "build_id": orphan_candidate_id,
                "subject": _subject("removed-project", revision_id),
                "manifest_sha256": "e" * 64,
            },
        },
        "candidate_test_qualifications": {
            qualification_id: {
                "qualification_id": qualification_id,
                "subject": _subject("demo", revision_id),
                "builds": [{"build_id": candidate_id}],
                "manifest_sha256": "f" * 64,
            }
        },
        "tested_merge_attestations": {
            attestation_id: {
                "attestation_id": attestation_id,
                "qualification_id": qualification_id,
                "merged_revision": {
                    "project": "demo",
                    "revision_id": revision_id,
                },
                "manifest_sha256": "1" * 64,
            }
        },
        "database_backups": {
            backup_id: {
                "backup_id": backup_id,
                "source": {"location_id": _location_id(database.path)},
                "manifest_sha256": "2" * 64,
            },
            orphan_backup_id: {
                "backup_id": orphan_backup_id,
                "source": {"location_id": "0" * 64},
                "manifest_sha256": "3" * 64,
            },
        },
    }
    service = ArtifactReconciliationService(
        database,
        RetainedArtifactInventoryService(_families(tmp_path, evidence)),
    )
    try:
        first = service.report()
        second = service.report()
    finally:
        database.close()

    assert first == second
    assert first["format"] == ARTIFACT_RECONCILIATION_FORMAT
    assert first["complete"] is True
    assert len(first["reconciliation_id"]) == 64
    assert first["aggregate"]["counts"] == {
        "reachable": 7,
        "orphaned": 2,
        "missing": 1,
        "corrupt": 0,
        "staging": 0,
        "quarantined": 0,
        "lock_internal": 0,
        "unknown": 0,
    }
    by_family = {family["family"]: family for family in first["families"]}
    assert tuple(sorted(by_family)) == RETAINED_ARTIFACT_FAMILIES
    assert by_family["candidate_builds"]["counts"]["reachable"] == 1
    assert by_family["candidate_builds"]["counts"]["orphaned"] == 1
    assert by_family["test_runs"]["counts"]["reachable"] == 1
    assert by_family["test_runs"]["counts"]["missing"] == 1
    missing = by_family["test_runs"]["examples"]["missing"][0]
    assert missing["artifact_id"] == missing_run_id
    assert missing["entry_type"] == "missing"
    assert missing["required_by"] == [{"family": "test_batches", "artifact_id": batch_id}]

    encoded = json.dumps(first, sort_keys=True)
    assert str(tmp_path) not in encoded
    assert str(database.path) not in encoded


def test_existing_corrupt_target_is_not_reported_as_missing(
    tmp_path: Path,
) -> None:
    database, revision_id = _database(tmp_path)
    build_id = "a" * 32
    run_id = "b" * 32
    roots = {family: tmp_path / family for family in RETAINED_ARTIFACT_FAMILIES}
    for root in roots.values():
        root.mkdir()
    (roots["committed_builds"] / build_id).mkdir()
    (roots["test_runs"] / run_id).mkdir()

    def build_verifier(_artifact_id: str) -> dict[str, Any]:
        raise ValidationError("BROKEN_BUILD", "broken")

    def empty_verifier(_artifact_id: str) -> dict[str, Any]:
        return {}

    def run_verifier(_artifact_id: str) -> dict[str, Any]:
        return {
            "project": "demo",
            "revision_id": revision_id,
            "build_id": build_id,
            "manifest_sha256": "b" * 64,
        }

    families = []
    for family in RETAINED_ARTIFACT_FAMILIES:
        verifier = empty_verifier
        if family == "committed_builds":
            verifier = build_verifier
        elif family == "test_runs":
            verifier = run_verifier
        families.append(
            RetainedArtifactFamily(
                family,
                roots[family],
                _HEX64 if family == "database_backups" else _HEX32,
                verifier,
            )
        )

    try:
        report = ArtifactReconciliationService(
            database,
            RetainedArtifactInventoryService(families),
        ).report()
    finally:
        database.close()

    assert report["aggregate"]["counts"]["corrupt"] == 1
    assert report["aggregate"]["counts"]["missing"] == 0


def test_reconciliation_rejects_database_change_during_artifact_scan(
    tmp_path: Path,
) -> None:
    database, revision_id = _database(tmp_path)
    artifact_id = "a" * 32
    root = tmp_path / "builds"
    root.mkdir()
    (root / artifact_id).mkdir()
    changed = False

    def verify(_artifact_id: str) -> dict[str, Any]:
        nonlocal changed
        if not changed:
            changed = True
            project_id = database.connection.execute(
                "SELECT id FROM projects WHERE name = 'demo'"
            ).fetchone()[0]
            database.connection.execute(
                """INSERT INTO revisions(
                       id, project_id, parent1_id, message, author, root_hash
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    "revision-added-during-reconciliation",
                    project_id,
                    revision_id,
                    "concurrent change",
                    "test",
                    database.hash_value({}),
                ),
            )
            database.connection.commit()
        return {
            "project": "demo",
            "revision_id": revision_id,
            "manifest_sha256": "a" * 64,
        }

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
    try:
        with pytest.raises(ValidationError) as captured:
            ArtifactReconciliationService(database, inventory).report()
    finally:
        database.close()

    assert captured.value.code == "ARTIFACT_RECONCILIATION_DATABASE_CHANGED"


def test_reconciliation_accepts_exact_database_limit_and_rejects_plus_one(
    tmp_path: Path,
) -> None:
    database, revision_id = _database(tmp_path)
    root = tmp_path / "builds"
    root.mkdir()
    inventory = RetainedArtifactInventoryService(
        [
            RetainedArtifactFamily(
                "committed_builds",
                root,
                _HEX32,
                lambda _artifact_id: {},
            )
        ]
    )
    service = ArtifactReconciliationService(
        database,
        inventory,
        max_database_revisions=1,
    )
    assert service.report()["database"]["revision_count"] == 1

    project_id = database.connection.execute(
        "SELECT id FROM projects WHERE name = 'demo'"
    ).fetchone()[0]
    database.connection.execute(
        """INSERT INTO revisions(
               id, project_id, parent1_id, message, author, root_hash
           ) VALUES (?, ?, ?, ?, ?, ?)""",
        (
            "second-revision",
            project_id,
            revision_id,
            "second",
            "test",
            database.hash_value({}),
        ),
    )
    database.connection.commit()
    try:
        with pytest.raises(ValidationError) as captured:
            service.report()
    finally:
        database.close()

    assert captured.value.code == "ARTIFACT_RECONCILIATION_DATABASE_LIMIT_EXCEEDED"
