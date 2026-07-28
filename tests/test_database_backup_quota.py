from __future__ import annotations

from pathlib import Path

import pytest

from weave_frontend.artifact_quota import ArtifactQuotaService
from weave_frontend.artifact_storage import ArtifactStorageService
from weave_frontend.database import Database
from weave_frontend.errors import ArtifactIntegrityError, ArtifactQuotaExceededError
from weave_frontend.mcp_capabilities import PUBLIC_CAPABILITIES
from weave_frontend.verified_database_backup import DatabaseBackupService


def _initialized_database(path: Path) -> Database:
    database = Database(path)
    database.initialize_project("demo")
    return database


def _quota(root: Path, *, max_bytes: int) -> ArtifactQuotaService:
    return ArtifactQuotaService(
        ArtifactStorageService({"database_backups": root}),
        lock_path=root.parent / "quota.lock",
        max_bytes=max_bytes,
    )


def test_database_backup_is_an_explicit_artifact_storage_dependency() -> None:
    capabilities = {capability.name: capability for capability in PUBLIC_CAPABILITIES}
    names = [capability.name for capability in PUBLIC_CAPABILITIES]

    assert "database_backup" in capabilities["artifact_storage"].depends_on
    assert names.index("database_backup") < names.index("artifact_storage")


def test_database_backup_quota_rejects_before_immutable_publication(
    tmp_path: Path,
) -> None:
    backup_root = tmp_path / "backups"
    with _initialized_database(tmp_path / "source.db") as database:
        service = DatabaseBackupService(database, backup_root=backup_root)
        service.artifact_quota = _quota(backup_root, max_bytes=0)

        with pytest.raises(ArtifactQuotaExceededError) as captured:
            service.create()

    assert captured.value.family == "database_backups"
    assert captured.value.current_bytes == 0
    assert captured.value.staged_bytes > 0
    assert captured.value.projected_bytes == captured.value.staged_bytes
    assert list(backup_root.iterdir()) == []


def test_database_backup_quota_accounts_successful_publication(tmp_path: Path) -> None:
    backup_root = tmp_path / "backups"
    with _initialized_database(tmp_path / "source.db") as database:
        service = DatabaseBackupService(database, backup_root=backup_root)
        quota = _quota(backup_root, max_bytes=100 * 1024 * 1024)
        service.artifact_quota = quota

        backup = service.create()
        report = quota.report()

    assert (backup_root / backup["backup_id"]).is_dir()
    assert report["quota"]["current_logical_bytes"] > 0
    assert report["quota"]["current_logical_bytes"] == report["aggregate"][
        "logical_bytes"
    ]
    family = next(
        item for item in report["families"] if item["family"] == "database_backups"
    )
    assert family["logical_bytes"] == report["aggregate"]["logical_bytes"]


def test_database_backup_rejects_unbound_extra_files(tmp_path: Path) -> None:
    backup_root = tmp_path / "backups"
    with _initialized_database(tmp_path / "source.db") as database:
        service = DatabaseBackupService(database, backup_root=backup_root)
        backup = service.create()
        directory = backup_root / backup["backup_id"]
        (directory / "unbound-extra").write_bytes(b"not in the backup manifest")

        with pytest.raises(ArtifactIntegrityError, match="directory layout"):
            service.get(backup["backup_id"])
