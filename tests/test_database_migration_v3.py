from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from weave_frontend.database import Database
from weave_frontend.database_integrity import inspect_database

_GUARDS = (
    "revisions_validate_parent_projects_insert",
    "revisions_validate_parent_projects_update",
    "branches_validate_project_insert",
    "branches_validate_project_update",
)


def _downgrade_metadata_to_v2(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        for trigger in _GUARDS:
            connection.execute(f"DROP TRIGGER {trigger}")
        connection.execute("DROP INDEX uq_operations_revision_sequence")
        connection.execute("PRAGMA user_version = 2")
        connection.commit()
    finally:
        connection.close()


def test_clean_schema_v2_database_migrates_to_v3(tmp_path: Path) -> None:
    path = tmp_path / "clean-v2.db"
    with Database(path) as database:
        database.initialize_project("demo")
    _downgrade_metadata_to_v2(path)

    with Database(path) as migrated:
        assert migrated.connection.execute("PRAGMA user_version").fetchone()[0] == 3
        assert migrated.integrity_report()["valid"] is True
        guards = {
            str(row[0])
            for row in migrated.connection.execute(
                """SELECT name FROM sqlite_master
                   WHERE type = 'trigger' AND name LIKE '%validate%'
                   ORDER BY name"""
            ).fetchall()
        }
        assert set(_GUARDS) <= guards
        index = migrated.connection.execute(
            """SELECT 1 FROM sqlite_master
               WHERE type = 'index'
                 AND name = 'uq_operations_revision_sequence'"""
        ).fetchone()
        assert index is not None


def test_missing_core_table_blocks_migration(tmp_path: Path) -> None:
    path = tmp_path / "missing-operations.db"
    with Database(path) as database:
        database.initialize_project("demo")
    _downgrade_metadata_to_v2(path)

    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP TABLE operations")
        connection.commit()
    finally:
        connection.close()

    report = inspect_database(path)
    assert report["valid"] is False
    assert "operation_sequence_uniqueness" not in report["checked_invariants"]
    assert "operation_sequence_uniqueness" in report["skipped_invariants"]

    with pytest.raises(
        RuntimeError,
        match="MISSING_DATABASE_TABLES",
    ):
        Database(path)

    connection = sqlite3.connect(path)
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'operations'"
        ).fetchone() is None
    finally:
        connection.close()
