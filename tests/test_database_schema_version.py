from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from weave_frontend.database import Database, SCHEMA_VERSION


def test_future_schema_is_rejected_without_downgrading(tmp_path: Path) -> None:
    path = tmp_path / "future.db"
    future_version = SCHEMA_VERSION + 1

    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE future_marker(value TEXT NOT NULL)")
    connection.execute("INSERT INTO future_marker(value) VALUES ('preserve-me')")
    connection.execute(f"PRAGMA user_version = {future_version}")
    connection.commit()
    connection.close()

    with pytest.raises(RuntimeError, match="newer than supported"):
        Database(path)

    reopened = sqlite3.connect(path)
    try:
        assert reopened.execute("PRAGMA user_version").fetchone()[0] == future_version
        assert reopened.execute("SELECT value FROM future_marker").fetchone()[0] == "preserve-me"
    finally:
        reopened.close()


def test_current_schema_reopens_normally(tmp_path: Path) -> None:
    path = tmp_path / "current.db"
    with Database(path) as database:
        database.initialize_project("demo")
        assert database.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION

    with Database(path) as reopened:
        assert reopened.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert reopened.connection.execute("SELECT name FROM projects").fetchone()[0] == "demo"
