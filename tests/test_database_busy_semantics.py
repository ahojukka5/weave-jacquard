from __future__ import annotations

import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

import weave_jacquard
from weave_frontend.database import (
    DEFAULT_DATABASE_BUSY_TIMEOUT_MS,
    MAX_DATABASE_BUSY_TIMEOUT_MS,
    Database,
)
from weave_frontend.errors import DatabaseBusyError
from weave_frontend.mcp_server import _result


def test_database_configures_explicit_busy_timeout(tmp_path: Path) -> None:
    with Database(tmp_path / "jacquard.db", busy_timeout_ms=37) as database:
        configured = database.connection.execute("PRAGMA busy_timeout").fetchone()[0]

    assert configured == 37
    assert DEFAULT_DATABASE_BUSY_TIMEOUT_MS == 5_000


@pytest.mark.parametrize("value", [True, -1, MAX_DATABASE_BUSY_TIMEOUT_MS + 1, 1.5])
def test_database_rejects_invalid_busy_timeout(tmp_path: Path, value: object) -> None:
    with pytest.raises(ValueError, match="busy_timeout_ms"):
        Database(tmp_path / "jacquard.db", busy_timeout_ms=value)  # type: ignore[arg-type]


def test_database_busy_error_is_public() -> None:
    assert weave_jacquard.DatabaseBusyError is DatabaseBusyError


def test_busy_writer_returns_retryable_domain_error_and_recovers(tmp_path: Path) -> None:
    path = tmp_path / "jacquard.db"
    with (
        Database(path) as owner,
        Database(path, busy_timeout_ms=25) as contender,
    ):
        with owner.transaction() as connection:
            connection.execute(
                "INSERT INTO projects(id, name) VALUES (?, ?)",
                ("owner-project", "owner-project"),
            )
            with pytest.raises(DatabaseBusyError) as captured:
                with contender.transaction():
                    raise AssertionError("busy transaction unexpectedly started")

        error = captured.value
        assert error.code == "DATABASE_BUSY"
        assert error.as_dict() == {
            "code": "DATABASE_BUSY",
            "message": "database remained busy or locked for the configured timeout",
            "node_id": None,
            "retryable": True,
            "busy_timeout_ms": 25,
        }
        assert contender.connection.in_transaction is False

        with contender.transaction() as connection:
            connection.execute(
                "INSERT INTO projects(id, name) VALUES (?, ?)",
                ("contender-project", "contender-project"),
            )


def test_database_busy_error_uses_stable_mcp_envelope() -> None:
    def fail() -> None:
        raise DatabaseBusyError(busy_timeout_ms=125)

    assert _result(fail) == {
        "ok": False,
        "error": {
            "code": "DATABASE_BUSY",
            "message": "database remained busy or locked for the configured timeout",
            "node_id": None,
            "retryable": True,
            "busy_timeout_ms": 125,
        },
    }


def test_non_busy_operational_error_remains_operational_error(tmp_path: Path) -> None:
    with Database(tmp_path / "jacquard.db") as database:
        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            with database.transaction() as connection:
                connection.execute("INSERT INTO table_that_does_not_exist VALUES (1)")

        assert database.connection.in_transaction is False


def test_separate_process_writer_contention_is_stable(tmp_path: Path) -> None:
    path = tmp_path / "jacquard.db"
    ready = tmp_path / "writer-ready"
    with Database(path, busy_timeout_ms=50) as contender:
        script = """
import sqlite3
import sys
from pathlib import Path

connection = sqlite3.connect(sys.argv[1], timeout=0)
connection.execute("BEGIN IMMEDIATE")
Path(sys.argv[2]).write_text("ready", encoding="utf-8")
sys.stdin.readline()
connection.rollback()
connection.close()
"""
        process = subprocess.Popen(
            [sys.executable, "-c", script, str(path), str(ready)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + 5
            while not ready.exists() and process.poll() is None:
                if time.monotonic() >= deadline:
                    raise AssertionError("writer process did not acquire the database lock")
                time.sleep(0.01)
            assert process.poll() is None

            with pytest.raises(DatabaseBusyError) as startup_error:
                Database(path, busy_timeout_ms=50)
            assert startup_error.value.busy_timeout_ms == 50

            with pytest.raises(DatabaseBusyError) as transaction_error:
                with contender.transaction():
                    raise AssertionError("busy transaction unexpectedly started")

            assert transaction_error.value.busy_timeout_ms == 50
            assert contender.connection.in_transaction is False
        finally:
            stdout, stderr = process.communicate("\n", timeout=5)
            assert process.returncode == 0, (stdout, stderr)
