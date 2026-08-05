from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from weave_frontend.artifacts.reconciliation import (
    RETAINED_ARTIFACT_FAMILIES,
    RETAINED_ARTIFACT_INVENTORY_FORMAT,
    RetainedArtifactFamily,
    RetainedArtifactInventoryService,
)
from weave_frontend.errors import ValidationError

_HEX32 = re.compile(r"^[0-9a-f]{32}$")


def _family(
    name: str,
    root: Path,
    verifier: Any,
) -> RetainedArtifactFamily:
    return RetainedArtifactFamily(name, root, _HEX32, verifier)


def test_inventory_classifies_entries_without_exposing_paths(
    tmp_path: Path,
) -> None:
    root = tmp_path / "secret-retained-root"
    root.mkdir()
    verified_id = "a" * 32
    corrupt_id = "b" * 32
    wrong_type_id = "c" * 32
    symlink_id = "d" * 32
    (root / verified_id).mkdir()
    (root / corrupt_id).mkdir()
    (root / wrong_type_id).write_bytes(b"not-a-directory")
    (root / ".candidate-stage").mkdir()
    (root / ".candidate.replaced-deadbeef").mkdir()
    (root / ".candidate.lock").write_bytes(b"")
    (root / "operator-note").write_text("private", encoding="utf-8")
    (root / symlink_id).symlink_to(root / verified_id)

    calls: list[str] = []

    def verify(artifact_id: str) -> dict[str, str]:
        calls.append(artifact_id)
        if artifact_id == corrupt_id:
            raise ValidationError("BROKEN_ARTIFACT", "broken")
        return {"artifact_id": artifact_id}

    report = RetainedArtifactInventoryService([_family("committed_builds", root, verify)]).report()

    assert report["format"] == RETAINED_ARTIFACT_INVENTORY_FORMAT
    assert report["complete"] is True
    assert report["aggregate"]["counts"] == {
        "verified": 1,
        "corrupt": 2,
        "staging": 1,
        "quarantined": 1,
        "lock_internal": 1,
        "unknown": 2,
    }
    assert calls == [verified_id, corrupt_id]
    family = report["families"][0]
    assert family["entry_count"] == 8
    assert family["entries_scanned"] == 8
    assert len(family["family_catalog_id"]) == 64
    assert len(report["inventory_id"]) == 64

    encoded = json.dumps(report, sort_keys=True)
    assert str(root) not in encoded
    assert ".candidate-stage" not in encoded
    assert ".candidate.lock" not in encoded
    assert "operator-note" not in encoded
    assert (
        report
        == RetainedArtifactInventoryService([_family("committed_builds", root, verify)]).report()
    )


def test_inventory_accepts_exact_limits_and_rejects_limit_plus_one(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    for index in range(2):
        (root / f"entry-{index}").mkdir()

    service = RetainedArtifactInventoryService(
        [_family("committed_builds", root, lambda _artifact_id: {})],
        max_entries=2,
        max_entries_per_family=2,
    )
    assert service.report()["aggregate"]["entries_scanned"] == 2

    (root / "entry-2").mkdir()
    with pytest.raises(ValidationError) as captured:
        service.report()

    assert captured.value.code == "ARTIFACT_RECONCILIATION_SCAN_LIMIT_EXCEEDED"


def test_inventory_bounds_examples_without_losing_counts(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    for index in range(4):
        (root / f"unknown-{index}").mkdir()

    report = RetainedArtifactInventoryService(
        [_family("committed_builds", root, lambda _artifact_id: {})],
        max_examples=1,
    ).report()

    family = report["families"][0]
    assert family["counts"]["unknown"] == 4
    assert len(family["examples"]["unknown"]) == 1


def test_inventory_rejects_symlink_root(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    root = tmp_path / "linked-root"
    root.symlink_to(target, target_is_directory=True)

    with pytest.raises(ValidationError) as captured:
        RetainedArtifactInventoryService(
            [_family("committed_builds", root, lambda _artifact_id: {})]
        ).report()

    assert captured.value.code == "ARTIFACT_RECONCILIATION_ROOT_INVALID"


def test_inventory_excludes_direct_nested_family_root(tmp_path: Path) -> None:
    builds = tmp_path / "builds"
    candidates = builds / "candidates"
    builds.mkdir()
    candidates.mkdir()
    artifact_id = "a" * 32
    (candidates / artifact_id).mkdir()

    report = RetainedArtifactInventoryService(
        [
            _family("committed_builds", builds, lambda _artifact_id: {}),
            _family("candidate_builds", candidates, lambda _artifact_id: {}),
        ]
    ).report()

    by_family = {family["family"]: family for family in report["families"]}
    assert by_family["committed_builds"]["entry_count"] == 0
    assert by_family["committed_builds"]["entries_scanned"] == 1
    assert by_family["committed_builds"]["nested_roots"] == ["candidate_builds"]
    assert by_family["candidate_builds"]["counts"]["verified"] == 1


def test_inventory_fails_when_family_changes_during_verification(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    artifact_id = "a" * 32
    (root / artifact_id).mkdir()

    def verify(value: str) -> dict[str, str]:
        (root / "appeared-during-scan").mkdir()
        return {"artifact_id": value}

    with pytest.raises(ValidationError) as captured:
        RetainedArtifactInventoryService([_family("committed_builds", root, verify)]).report()

    assert captured.value.code == "ARTIFACT_RECONCILIATION_CHANGED_DURING_SCAN"


def test_inventory_declares_all_production_families() -> None:
    assert RETAINED_ARTIFACT_FAMILIES == (
        "candidate_builds",
        "candidate_test_qualifications",
        "committed_builds",
        "database_backups",
        "test_batches",
        "test_runs",
        "tested_merge_attestations",
    )
