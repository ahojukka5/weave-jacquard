from __future__ import annotations

import json
from pathlib import Path

import pytest

from weave_frontend.database import Database
from weave_frontend.database_integrity import inspect_database
from weave_frontend.errors import ArtifactIntegrityError, ValidationError
from weave_frontend.verified_database_backup import DatabaseBackupService


def _initialized_database(path: Path) -> Database:
    database = Database(path)
    database.initialize_project("demo")
    return database


def test_online_backup_is_content_derived_and_reverified(tmp_path: Path) -> None:
    source_path = tmp_path / "source.db"
    backup_root = tmp_path / "backups"
    with _initialized_database(source_path) as database:
        service = DatabaseBackupService(database, backup_root=backup_root)

        created = service.create()
        inspected = service.get(created["backup_id"])

        assert len(created["backup_id"]) == 64
        assert created["cached"] is False
        assert inspected["backup_id"] == created["backup_id"]
        assert inspected["manifest_sha256"] == created["manifest_sha256"]
        assert inspected["integrity"]["valid"] is True
        assert inspected["source"]["journal_mode"] == "wal"
        assert inspected["backup_database"]["journal_mode"] == "delete"
        assert "sqlite_version" not in inspected["source"]
        assert "sqlite_version" not in inspected["backup_database"]
        assert inspected["artifact_bytes"]["database"] > 0
        assert len(inspected["artifact_sha256"]["database"]) == 64
        directory = backup_root / created["backup_id"]
        assert (directory / "database.sqlite3").is_file()
        assert (directory / "backup-manifest.json").is_file()
        assert not Path(str(directory / "database.sqlite3") + "-wal").exists()
        assert not Path(str(directory / "database.sqlite3") + "-shm").exists()
        assert not Path(str(directory / "database.sqlite3") + "-journal").exists()


def test_unchanged_database_reuses_verified_backup(tmp_path: Path) -> None:
    source_path = tmp_path / "source.db"
    with _initialized_database(source_path) as database:
        service = DatabaseBackupService(database, backup_root=tmp_path / "backups")

        first = service.create()
        second = service.create()

        assert second["backup_id"] == first["backup_id"]
        assert second["manifest_sha256"] == first["manifest_sha256"]
        assert first["cached"] is False
        assert second["cached"] is True


def test_database_change_produces_new_backup_identity(tmp_path: Path) -> None:
    source_path = tmp_path / "source.db"
    with _initialized_database(source_path) as database:
        service = DatabaseBackupService(database, backup_root=tmp_path / "backups")
        first = service.create()

        database.initialize_project("second-project")
        second = service.create()

        assert second["backup_id"] != first["backup_id"]
        assert (
            second["artifact_sha256"]["database"]
            != first["artifact_sha256"]["database"]
        )


def test_backup_refuses_active_source_transaction(tmp_path: Path) -> None:
    with _initialized_database(tmp_path / "source.db") as database:
        service = DatabaseBackupService(database, backup_root=tmp_path / "backups")
        database.connection.execute("BEGIN IMMEDIATE")
        try:
            with pytest.raises(ValidationError) as captured:
                service.create()
        finally:
            database.connection.rollback()

    assert captured.value.code == "DATABASE_BACKUP_TRANSACTION_ACTIVE"


@pytest.mark.parametrize("timeout", [True, 0, -1, 3601, 1.5])
def test_backup_rejects_invalid_timeout(tmp_path: Path, timeout: object) -> None:
    with _initialized_database(tmp_path / "source.db") as database:
        service = DatabaseBackupService(database, backup_root=tmp_path / "backups")

        with pytest.raises(ValidationError) as captured:
            service.create(timeout_seconds=timeout)  # type: ignore[arg-type]

    assert captured.value.code == "INVALID_DATABASE_BACKUP_TIMEOUT"


def test_backup_detects_database_artifact_corruption(tmp_path: Path) -> None:
    with _initialized_database(tmp_path / "source.db") as database:
        service = DatabaseBackupService(database, backup_root=tmp_path / "backups")
        backup = service.create()
        database_path = (
            service.backup_root / backup["backup_id"] / "database.sqlite3"
        )
        payload = bytearray(database_path.read_bytes())
        payload[-1] ^= 0xFF
        database_path.write_bytes(payload)

        with pytest.raises(ArtifactIntegrityError):
            service.get(backup["backup_id"])


def test_backup_detects_manifest_cache_state_tampering(tmp_path: Path) -> None:
    with _initialized_database(tmp_path / "source.db") as database:
        service = DatabaseBackupService(database, backup_root=tmp_path / "backups")
        backup = service.create()
        manifest_path = (
            service.backup_root / backup["backup_id"] / "backup-manifest.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["cached"] = True
        manifest_path.write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

        with pytest.raises(ArtifactIntegrityError, match="cache state"):
            service.get(backup["backup_id"])


def test_backup_manifest_reader_rejects_oversized_metadata(tmp_path: Path) -> None:
    backup_id = "a" * 64
    backup_root = tmp_path / "backups"
    directory = backup_root / backup_id
    directory.mkdir(parents=True)
    (directory / "backup-manifest.json").write_text(
        "{" + '"padding":"' + "x" * (1024 * 1024) + '"}',
        encoding="utf-8",
    )
    service = DatabaseBackupService(None, backup_root=backup_root)

    with pytest.raises(ArtifactIntegrityError, match="exceeds"):
        service.get(backup_id)


def test_backup_directory_symlink_is_rejected(tmp_path: Path) -> None:
    backup_id = "b" * 64
    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    target = tmp_path / "outside"
    target.mkdir()
    (backup_root / backup_id).symlink_to(target, target_is_directory=True)
    service = DatabaseBackupService(None, backup_root=backup_root)

    with pytest.raises(ArtifactIntegrityError, match="non-symlink"):
        service.get(backup_id)


def test_restore_publishes_new_valid_offline_database(tmp_path: Path) -> None:
    source_path = tmp_path / "source.db"
    backup_root = tmp_path / "backups"
    with _initialized_database(source_path) as database:
        service = DatabaseBackupService(database, backup_root=backup_root)
        backup = service.create()

    offline_store = DatabaseBackupService(None, backup_root=backup_root)
    destination = tmp_path / "restored.db"
    restored = offline_store.restore(backup["backup_id"], destination)

    assert restored["destination"] == str(destination.resolve())
    assert restored["database_sha256"] == backup["artifact_sha256"]["database"]
    assert restored["database_bytes"] == backup["artifact_bytes"]["database"]
    assert restored["integrity_valid"] is True
    assert inspect_database(destination)["valid"] is True
    with Database(destination) as database:
        projects = database.connection.execute(
            "SELECT name FROM projects ORDER BY name"
        ).fetchall()
    assert [row["name"] for row in projects] == ["demo"]


def test_restore_refuses_existing_destination_and_sidecars(tmp_path: Path) -> None:
    source_path = tmp_path / "source.db"
    backup_root = tmp_path / "backups"
    with _initialized_database(source_path) as database:
        backup = DatabaseBackupService(
            database,
            backup_root=backup_root,
        ).create()
    service = DatabaseBackupService(None, backup_root=backup_root)

    destination = tmp_path / "restored.db"
    destination.write_bytes(b"existing")
    with pytest.raises(ValidationError) as captured:
        service.restore(backup["backup_id"], destination)
    assert captured.value.code == "DATABASE_RESTORE_DESTINATION_EXISTS"
    assert destination.read_bytes() == b"existing"

    destination.unlink()
    sidecar = Path(str(destination) + "-wal")
    sidecar.write_bytes(b"existing-sidecar")
    with pytest.raises(ValidationError) as captured:
        service.restore(backup["backup_id"], destination)
    assert captured.value.code == "DATABASE_RESTORE_DESTINATION_EXISTS"
    assert not destination.exists()
    assert sidecar.read_bytes() == b"existing-sidecar"


def test_restore_refuses_destination_inside_backup_store(tmp_path: Path) -> None:
    source_path = tmp_path / "source.db"
    backup_root = tmp_path / "backups"
    with _initialized_database(source_path) as database:
        backup = DatabaseBackupService(
            database,
            backup_root=backup_root,
        ).create()
    service = DatabaseBackupService(None, backup_root=backup_root)

    with pytest.raises(ValidationError) as captured:
        service.restore(backup["backup_id"], backup_root / "restored.db")

    assert captured.value.code == "INVALID_DATABASE_RESTORE_DESTINATION"


def test_failed_restore_leaves_no_destination_or_temporary_file(tmp_path: Path) -> None:
    source_path = tmp_path / "source.db"
    backup_root = tmp_path / "backups"
    with _initialized_database(source_path) as database:
        service = DatabaseBackupService(database, backup_root=backup_root)
        backup = service.create()
        database_path = backup_root / backup["backup_id"] / "database.sqlite3"
        database_path.write_bytes(b"corrupt")

    destination = tmp_path / "restored.db"
    with pytest.raises(ArtifactIntegrityError):
        DatabaseBackupService(None, backup_root=backup_root).restore(
            backup["backup_id"],
            destination,
        )

    assert not destination.exists()
    assert list(tmp_path.glob(".restored.db.restore-*")) == []
