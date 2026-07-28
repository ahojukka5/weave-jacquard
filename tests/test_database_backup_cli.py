from __future__ import annotations

import os
from pathlib import Path

from weave_frontend.build_cli import _execute, build_parser
from weave_frontend.database import Database


def test_backup_cli_creates_inspects_and_restores_without_source_database(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.db"
    backup_root = tmp_path / "backups"
    with Database(source) as database:
        database.initialize_project("demo")

    parser = build_parser()
    create_args = parser.parse_args(
        [
            "--db",
            str(source),
            "--backup-root",
            str(backup_root),
            "db-backup",
            "--timeout-seconds",
            "30",
        ]
    )
    created = _execute(create_args)
    backup_id = created["backup_id"]

    for suffix in ("", "-wal", "-shm", "-journal"):
        path = Path(str(source) + suffix)
        if os.path.lexists(path):
            path.unlink()

    inspect_args = parser.parse_args(
        [
            "--db",
            str(source),
            "--backup-root",
            str(backup_root),
            "db-backup-get",
            backup_id,
        ]
    )
    inspected = _execute(inspect_args)
    assert inspected["backup_id"] == backup_id
    assert not source.exists()

    destination = tmp_path / "restored.db"
    restore_args = parser.parse_args(
        [
            "--db",
            str(source),
            "--backup-root",
            str(backup_root),
            "db-restore",
            backup_id,
            str(destination),
        ]
    )
    restored = _execute(restore_args)

    assert restored["backup_id"] == backup_id
    assert destination.is_file()
    assert not source.exists()
    with Database(destination) as database:
        names = database.connection.execute(
            "SELECT name FROM projects ORDER BY name"
        ).fetchall()
    assert [row["name"] for row in names] == ["demo"]


def test_backup_cli_defaults_store_next_to_database(tmp_path: Path) -> None:
    source = tmp_path / "nested" / "source.db"
    with Database(source) as database:
        database.initialize_project("demo")

    args = build_parser().parse_args(
        ["--db", str(source), "db-backup"]
    )
    created = _execute(args)

    assert (
        source.parent
        / ".weave-database-backups"
        / created["backup_id"]
        / "backup-manifest.json"
    ).is_file()
