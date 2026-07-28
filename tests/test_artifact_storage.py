from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import weave_frontend.artifact_storage as storage_module
import weave_frontend.mcp_artifact_storage as mcp_storage_module
from weave_frontend.artifact_storage import (
    ARTIFACT_STORAGE_REPORT_FORMAT,
    ArtifactStorageService,
)
from weave_frontend.errors import ValidationError


def test_storage_report_accounts_nested_roots_once(tmp_path: Path) -> None:
    builds = tmp_path / "builds"
    candidates = builds / "merge-candidates"
    builds.mkdir()
    candidates.mkdir()
    (builds / "committed.bin").write_bytes(b"abc")
    (candidates / "candidate.bin").write_bytes(b"12345")

    report = ArtifactStorageService(
        {
            "committed_builds": builds,
            "candidate_builds": candidates,
        }
    ).report()

    assert report["format"] == ARTIFACT_STORAGE_REPORT_FORMAT
    assert report["complete"] is True
    assert report["aggregate"] == {
        "logical_bytes": 8,
        "regular_files": 2,
        "directories": 2,
        "symlinks": 0,
        "special_entries": 0,
        "entries_scanned": 3,
        "root_count": 2,
    }
    by_family = {item["family"]: item for item in report["families"]}
    assert by_family["committed_builds"]["logical_bytes"] == 3
    assert by_family["committed_builds"]["nested_roots"] == ["candidate_builds"]
    assert by_family["candidate_builds"]["logical_bytes"] == 5
    assert by_family["candidate_builds"]["nested_roots"] == []
    assert len(report["storage_snapshot_id"]) == 64
    assert report == ArtifactStorageService(
        {
            "committed_builds": builds,
            "candidate_builds": candidates,
        }
    ).report()


def test_storage_report_redacts_root_paths(tmp_path: Path) -> None:
    root = tmp_path / "secret-artifact-root"
    root.mkdir()
    (root / "artifact").write_bytes(b"payload")

    report = ArtifactStorageService({"builds": root}).report()

    encoded = json.dumps(report, sort_keys=True)
    assert str(root) not in encoded
    assert report["families"][0]["root_id"]


def test_storage_report_counts_symlinks_without_following(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_bytes(b"not-counted")
    (root / "link").symlink_to(outside)

    report = ArtifactStorageService({"builds": root}).report()

    assert report["aggregate"]["logical_bytes"] == 0
    assert report["aggregate"]["regular_files"] == 0
    assert report["aggregate"]["symlinks"] == 1


def test_storage_report_rejects_duplicate_resolved_roots(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()

    with pytest.raises(ValidationError) as captured:
        ArtifactStorageService({"first": root, "second": root}).report()

    assert captured.value.code == "ARTIFACT_STORAGE_ROOT_CONFLICT"


def test_storage_report_accepts_exact_global_entry_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    for index in range(3):
        (root / f"artifact-{index}").write_bytes(b"x")
    monkeypatch.setattr(storage_module, "MAX_ARTIFACT_SCAN_ENTRIES", 3)

    report = ArtifactStorageService({"builds": root}).report()

    assert report["aggregate"]["entries_scanned"] == 3
    assert report["aggregate"]["logical_bytes"] == 3


def test_storage_report_rejects_global_entry_limit_plus_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    for index in range(4):
        (root / f"artifact-{index}").write_bytes(b"x")
    monkeypatch.setattr(storage_module, "MAX_ARTIFACT_SCAN_ENTRIES", 3)

    with pytest.raises(ValidationError) as captured:
        ArtifactStorageService({"builds": root}).report()

    assert captured.value.code == "ARTIFACT_STORAGE_SCAN_LIMIT_EXCEEDED"


def test_storage_report_rejects_depth_overflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "artifacts"
    nested = root / "one" / "two"
    nested.mkdir(parents=True)
    monkeypatch.setattr(storage_module, "MAX_ARTIFACT_SCAN_DEPTH", 1)

    with pytest.raises(ValidationError) as captured:
        ArtifactStorageService({"builds": root}).report()

    assert captured.value.code == "ARTIFACT_STORAGE_DEPTH_EXCEEDED"


def test_production_root_composition_includes_every_artifact_family(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots = {
        "committed_builds": tmp_path / "builds",
        "candidate_builds": tmp_path / "candidates",
        "test_runs": tmp_path / "runs",
        "test_batches": tmp_path / "batches",
        "candidate_test_qualifications": tmp_path / "qualifications",
        "tested_merge_attestations": tmp_path / "attestations",
    }
    monkeypatch.setattr(
        mcp_storage_module,
        "compiler_bridge",
        lambda: SimpleNamespace(build_root=roots["committed_builds"]),
    )
    monkeypatch.setattr(
        mcp_storage_module,
        "merge_candidate_builds",
        lambda: SimpleNamespace(build_root=roots["candidate_builds"]),
    )
    monkeypatch.setattr(
        mcp_storage_module,
        "test_runs",
        lambda: SimpleNamespace(run_root=roots["test_runs"]),
    )
    monkeypatch.setattr(
        mcp_storage_module,
        "test_batches",
        lambda: SimpleNamespace(batch_root=roots["test_batches"]),
    )
    monkeypatch.setattr(
        mcp_storage_module,
        "merge_candidate_test_batches",
        lambda: SimpleNamespace(run_root=roots["candidate_test_qualifications"]),
    )
    monkeypatch.setattr(
        mcp_storage_module,
        "tested_merge_attestations",
        lambda: SimpleNamespace(attestation_root=roots["tested_merge_attestations"]),
    )

    assert mcp_storage_module._artifact_roots() == roots
