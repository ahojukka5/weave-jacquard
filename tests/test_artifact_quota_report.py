from __future__ import annotations

from pathlib import Path

from weave_frontend.artifacts.quota import ArtifactQuotaService
from weave_frontend.artifacts.storage import ArtifactStorageService


def test_quota_report_separates_retained_and_internal_staging_bytes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    retained = root / ("a" * 32)
    retained.mkdir(parents=True)
    (retained / "artifact").write_bytes(b"1234")
    stage = root / ".pending-stage"
    stage.mkdir()
    (stage / "artifact").write_bytes(b"abc")
    quota = ArtifactQuotaService(
        ArtifactStorageService({"committed_builds": root}),
        lock_path=tmp_path / "quota.lock",
        max_bytes=6,
    )

    report = quota.report()

    assert report["aggregate"]["logical_bytes"] == 7
    assert report["quota"]["observed_logical_bytes"] == 7
    assert report["quota"]["internal_logical_bytes"] == 3
    assert report["quota"]["current_logical_bytes"] == 4
    assert report["quota"]["available_logical_bytes"] == 2
    assert report["quota"]["exceeded"] is False
    assert report["quota"]["retained_storage_snapshot_id"]


def test_quota_report_exceeded_state_uses_retained_bytes(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    retained = root / ("a" * 32)
    retained.mkdir(parents=True)
    (retained / "artifact").write_bytes(b"1234")
    quota = ArtifactQuotaService(
        ArtifactStorageService({"committed_builds": root}),
        lock_path=tmp_path / "quota.lock",
        max_bytes=3,
    )

    report = quota.report()

    assert report["quota"]["current_logical_bytes"] == 4
    assert report["quota"]["available_logical_bytes"] == 0
    assert report["quota"]["exceeded"] is True
