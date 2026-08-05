from __future__ import annotations

from pathlib import Path

from weave_frontend.database import Database
from weave_frontend.database_backup import (
    DatabaseBackupService as LegacyKeyDatabaseBackupService,
)
from weave_frontend.database_integrity import (
    DATABASE_SEMANTIC_INTEGRITY_CONTRACT,
)
from weave_frontend.verified_database_backup import DatabaseBackupService


def test_backup_identity_binds_semantic_integrity_contract(tmp_path: Path) -> None:
    database_path = tmp_path / "source.db"
    with Database(database_path) as database:
        database.initialize_project("demo")
        service = DatabaseBackupService(
            database,
            backup_root=tmp_path / "backups",
        )
        backup = service.create()

    assert backup["integrity"]["semantic_contract"] == (DATABASE_SEMANTIC_INTEGRITY_CONTRACT)
    assert backup["backup_key"]["semantic_integrity_contract"] == (
        DATABASE_SEMANTIC_INTEGRITY_CONTRACT
    )

    legacy_key = LegacyKeyDatabaseBackupService._backup_key(
        source=backup["source"],
        backup_database=backup["backup_database"],
        artifact_identity={
            "bytes": backup["artifact_bytes"]["database"],
            "sha256": backup["artifact_sha256"]["database"],
        },
    )
    assert "semantic_integrity_contract" not in legacy_key
    assert service._hash_json(legacy_key) != backup["backup_id"]
