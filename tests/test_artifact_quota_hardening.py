from __future__ import annotations

import os
from pathlib import Path

import pytest

from weave_frontend.artifact_quota import ArtifactQuotaService
from weave_frontend.artifact_storage import ArtifactStorageService
from weave_frontend.errors import ArtifactQuotaExceededError, ValidationError


def _quota(
    root: Path,
    *,
    max_bytes: int,
    lock_path: Path | None = None,
) -> ArtifactQuotaService:
    return ArtifactQuotaService(
        ArtifactStorageService({"committed_builds": root}),
        lock_path=lock_path or root.parent / "quota.lock",
        max_bytes=max_bytes,
    )


def test_replacement_excludes_old_final_and_counts_new_stage(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    retained = root / ("1" * 32)
    retained.mkdir()
    (retained / "artifact").write_bytes(b"1234")
    final = root / ("2" * 32)
    final.mkdir()
    (final / "artifact").write_bytes(b"12345")
    temporary = root / ".replacement-stage"
    temporary.mkdir()
    (temporary / "artifact").write_bytes(b"abc")
    quota = _quota(root, max_bytes=7)

    with quota.admit(
        family="committed_builds",
        temporary=temporary,
        final=final,
    ) as evidence:
        assert evidence is not None
        assert evidence["current_bytes"] == 4
        assert evidence["staged_bytes"] == 3
        assert evidence["projected_bytes"] == 7
        old = root / ".old-final"
        os.replace(final, old)
        os.replace(temporary, final)
        for child in old.iterdir():
            child.unlink()
        old.rmdir()

    assert quota.report()["aggregate"]["logical_bytes"] == 7


def test_hidden_files_inside_completed_artifacts_remain_in_quota(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    final = root / ("a" * 32)
    final.mkdir(parents=True)
    (final / ".hidden-evidence").write_bytes(b"1234")
    temporary = root / ".new-stage"
    temporary.mkdir()
    (temporary / "artifact").write_bytes(b"abc")
    quota = _quota(root, max_bytes=6)

    with (
        pytest.raises(ArtifactQuotaExceededError) as captured,
        quota.admit(
            family="committed_builds",
            temporary=temporary,
            final=root / ("b" * 32),
        ),
    ):
        raise AssertionError("hidden retained bytes were not counted")

    assert captured.value.projected_bytes == 7


def test_exact_stage_rejects_symlink_directory(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    temporary = root / ".stage"
    temporary.symlink_to(target, target_is_directory=True)
    quota = _quota(root, max_bytes=10)

    with (
        pytest.raises(ValidationError) as captured,
        quota.admit(
            family="committed_builds",
            temporary=temporary,
            final=root / ("a" * 32),
        ),
    ):
        raise AssertionError("symlink stage unexpectedly admitted")

    assert captured.value.code == "INVALID_ARTIFACT_QUOTA_PATH"


def test_quota_lock_rejects_symlink_without_following(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    target = tmp_path / "target-lock"
    target.write_text("", encoding="utf-8")
    lock_path = tmp_path / "quota.lock"
    lock_path.symlink_to(target)
    quota = _quota(root, max_bytes=10, lock_path=lock_path)

    with pytest.raises(ValidationError) as captured:
        quota.report()

    assert captured.value.code == "ARTIFACT_STORAGE_QUOTA_LOCK_UNAVAILABLE"


def test_final_symlink_is_not_followed_for_replacement_accounting(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_artifact = outside / "artifact"
    outside_artifact.write_bytes(b"123456789")
    final = root / ("a" * 32)
    final.symlink_to(outside, target_is_directory=True)
    temporary = root / ".new-stage"
    temporary.mkdir()
    (temporary / "artifact").write_bytes(b"abc")
    quota = _quota(root, max_bytes=3)

    with quota.admit(
        family="committed_builds",
        temporary=temporary,
        final=final,
    ) as evidence:
        assert evidence is not None
        assert evidence["current_bytes"] == 0
        assert evidence["staged_bytes"] == 3

    assert final.is_symlink()
    assert outside_artifact.read_bytes() == b"123456789"
