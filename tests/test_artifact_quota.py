from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import weave_frontend.artifact_quota as quota_module
from weave_frontend.artifact_quota import (
    MAX_ARTIFACT_QUOTA_BYTES,
    ArtifactQuotaService,
    artifact_quota_admission,
    parse_artifact_quota,
)
from weave_frontend.artifact_storage import ArtifactStorageService
from weave_frontend.errors import ArtifactQuotaExceededError, ValidationError
from weave_frontend.mcp_server import _result


def _quota(root: Path, *, max_bytes: int | None) -> ArtifactQuotaService:
    return ArtifactQuotaService(
        ArtifactStorageService({"committed_builds": root}),
        lock_path=root.parent / "quota.lock",
        max_bytes=max_bytes,
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("", None),
        ("0", 0),
        ("17", 17),
        (str(MAX_ARTIFACT_QUOTA_BYTES), MAX_ARTIFACT_QUOTA_BYTES),
    ],
)
def test_parse_artifact_quota(value: str | None, expected: int | None) -> None:
    assert parse_artifact_quota(value) == expected


@pytest.mark.parametrize(
    "value",
    [" 1", "1 ", "+1", "-1", "1.0", "１２", str(MAX_ARTIFACT_QUOTA_BYTES + 1)],
)
def test_parse_artifact_quota_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError, match="WEAVE_ARTIFACT_MAX_BYTES"):
        parse_artifact_quota(value)


def test_quota_report_binds_enabled_policy_without_paths(tmp_path: Path) -> None:
    root = tmp_path / "secret-artifacts"
    root.mkdir()
    (root / "artifact").write_bytes(b"abcd")
    quota = _quota(root, max_bytes=10)

    report = quota.report()

    assert report["aggregate"]["logical_bytes"] == 4
    assert report["quota"]["enabled"] is True
    assert report["quota"]["max_logical_bytes"] == 10
    assert report["quota"]["available_logical_bytes"] == 6
    assert report["quota"]["exceeded"] is False
    assert len(report["quota"]["quota_policy_id"]) == 64
    assert len(report["quota_snapshot_id"]) == 64
    encoded = json.dumps(report, sort_keys=True)
    assert str(root) not in encoded
    assert str(quota.lock_path) not in encoded


def test_disabled_quota_preserves_publication_without_lock(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    temporary = root / ".build-stage"
    temporary.mkdir()
    (temporary / "artifact").write_bytes(b"payload")
    final = root / ("a" * 32)
    quota = _quota(root, max_bytes=None)

    with quota.admit(
        family="committed_builds",
        temporary=temporary,
        final=final,
    ) as evidence:
        assert evidence is None
        os.replace(temporary, final)

    assert final.is_dir()
    assert not quota.lock_path.exists()


def test_exact_stage_accepts_quota_boundary_and_publishes(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    existing = root / ("1" * 32)
    existing.mkdir()
    (existing / "artifact").write_bytes(b"1234")
    temporary = root / ".new-build-stage"
    temporary.mkdir()
    (temporary / "artifact").write_bytes(b"abc")
    final = root / ("2" * 32)
    quota = _quota(root, max_bytes=7)

    with quota.admit(
        family="committed_builds",
        temporary=temporary,
        final=final,
    ) as evidence:
        assert evidence is not None
        assert evidence["family"] == "committed_builds"
        assert evidence["quota_bytes"] == 7
        assert evidence["current_bytes"] == 4
        assert evidence["staged_bytes"] == 3
        assert evidence["projected_bytes"] == 7
        assert len(evidence["storage_snapshot_id"]) == 64
        os.replace(temporary, final)

    assert quota.report()["aggregate"]["logical_bytes"] == 7


def test_exact_stage_rejects_limit_plus_one_with_stable_error(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    existing = root / ("1" * 32)
    existing.mkdir()
    (existing / "artifact").write_bytes(b"1234")
    temporary = root / ".new-build-stage"
    temporary.mkdir()
    (temporary / "artifact").write_bytes(b"abc")
    final = root / ("2" * 32)
    quota = _quota(root, max_bytes=6)

    with (
        pytest.raises(ArtifactQuotaExceededError) as captured,
        quota.admit(
            family="committed_builds",
            temporary=temporary,
            final=final,
        ),
    ):
        raise AssertionError("overflowing publication unexpectedly admitted")

    assert captured.value.as_dict() == {
        "code": "ARTIFACT_STORAGE_QUOTA_EXCEEDED",
        "message": ("artifact publication would exceed the configured logical-byte quota"),
        "node_id": None,
        "retryable": False,
        "requires_operator_action": True,
        "family": "committed_builds",
        "quota_bytes": 6,
        "current_bytes": 4,
        "staged_bytes": 3,
        "projected_bytes": 7,
    }
    assert temporary.is_dir()
    assert not final.exists()


def test_quota_error_uses_stable_mcp_envelope() -> None:
    def fail() -> None:
        raise ArtifactQuotaExceededError(
            family="test_runs",
            quota_bytes=10,
            current_bytes=8,
            staged_bytes=3,
            projected_bytes=11,
        )

    expected = {
        "code": "ARTIFACT_STORAGE_QUOTA_EXCEEDED",
        "message": "artifact publication would exceed the configured logical-byte quota",
        "node_id": None,
        "retryable": False,
        "requires_operator_action": True,
        "family": "test_runs",
        "quota_bytes": 10,
        "current_bytes": 8,
        "staged_bytes": 3,
        "projected_bytes": 11,
    }
    assert _result(fail) == {"ok": False, "error": expected}


def test_prefix_admission_ignores_other_staging_then_prevents_oversubscription(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    first_final = root / ("1" * 32)
    second_final = root / ("2" * 32)
    first_stage = root / f".{first_final.name}-first"
    second_stage = root / f".{second_final.name}-second"
    first_stage.mkdir()
    second_stage.mkdir()
    (first_stage / "artifact").write_bytes(b"123456")
    (second_stage / "artifact").write_bytes(b"abcdef")
    quota = _quota(root, max_bytes=10)

    with quota.admit_staged_prefix(
        family="committed_builds",
        final=first_final,
    ) as evidence:
        assert evidence is not None
        assert evidence["current_bytes"] == 0
        assert evidence["staged_bytes"] == 6
        os.replace(first_stage, first_final)

    with (
        pytest.raises(ArtifactQuotaExceededError) as captured,
        quota.admit_staged_prefix(
            family="committed_builds",
            final=second_final,
        ),
    ):
        raise AssertionError("second publication unexpectedly admitted")

    assert captured.value.current_bytes == 6
    assert captured.value.staged_bytes == 6
    assert captured.value.projected_bytes == 12
    assert second_stage.is_dir()


def test_prefix_admission_uses_largest_duplicate_stage(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    final = root / ("a" * 32)
    smaller = root / f".{final.name}-small"
    larger = root / f".{final.name}-large"
    smaller.mkdir()
    larger.mkdir()
    (smaller / "artifact").write_bytes(b"123")
    (larger / "artifact").write_bytes(b"1234")
    quota = _quota(root, max_bytes=4)

    with quota.admit_staged_prefix(
        family="committed_builds",
        final=final,
    ) as evidence:
        assert evidence is not None
        assert evidence["staged_bytes"] == 4


def test_prefix_admission_rejects_missing_stage(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    quota = _quota(root, max_bytes=10)

    with (
        pytest.raises(ValidationError) as captured,
        quota.admit_staged_prefix(
            family="committed_builds",
            final=root / ("a" * 32),
        ),
    ):
        raise AssertionError("missing stage unexpectedly admitted")

    assert captured.value.code == "ARTIFACT_STORAGE_STAGE_NOT_FOUND"


def test_attached_admission_is_optional_for_direct_service_instances(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    temporary = root / ".stage"
    temporary.mkdir()
    final = root / ("a" * 32)
    owner = object()

    with artifact_quota_admission(
        owner,
        family="committed_builds",
        temporary=temporary,
        final=final,
    ) as evidence:
        assert evidence is None


def test_staged_candidate_count_is_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    final = root / ("a" * 32)
    monkeypatch.setattr(quota_module, "MAX_ARTIFACT_STAGED_CANDIDATES", 1)
    for suffix in ("first", "second"):
        stage = root / f".{final.name}-{suffix}"
        stage.mkdir()
    quota = _quota(root, max_bytes=10)

    with (
        pytest.raises(ValidationError) as captured,
        quota.admit_staged_prefix(
            family="committed_builds",
            final=final,
        ),
    ):
        raise AssertionError("excess stages unexpectedly admitted")

    assert captured.value.code == "ARTIFACT_STORAGE_STAGE_LIMIT_EXCEEDED"
