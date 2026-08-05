from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from weave_frontend.build_cli import _execute, build_parser
from weave_frontend.database import SCHEMA_VERSION, Database
from weave_frontend.database_integrity import inspect_connection, inspect_database


def _two_projects(path: Path) -> tuple[str, str, str, str]:
    with Database(path) as database:
        left_project, left_revision = database.initialize_project("left")
        right_project, right_revision = database.initialize_project("right")
    return left_project, left_revision, right_project, right_revision


def _manufacture_legacy_corruption(path: Path) -> None:
    left_project, left_revision, right_project, right_revision = _two_projects(path)
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys = OFF")
        for trigger in (
            "revisions_validate_parent_projects_insert",
            "revisions_validate_parent_projects_update",
            "branches_validate_project_insert",
            "branches_validate_project_update",
        ):
            connection.execute(f"DROP TRIGGER {trigger}")
        connection.execute("DROP INDEX uq_operations_revision_sequence")
        connection.execute("PRAGMA user_version = 2")

        cross_parent = str(uuid4())
        connection.execute(
            """INSERT INTO revisions(
                   id, project_id, parent1_id, message, author, root_hash
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                cross_parent,
                left_project,
                right_revision,
                "cross-project parent",
                "corruptor",
                "0" * 64,
            ),
        )
        connection.execute(
            """INSERT INTO branches(project_id, name, head_revision_id)
               VALUES (?, ?, ?)""",
            (left_project, "foreign-head", right_revision),
        )
        for operation_id in (str(uuid4()), str(uuid4())):
            connection.execute(
                """INSERT INTO operations(
                       id, revision_id, sequence_number, operation_kind, payload_json
                   ) VALUES (?, ?, 0, 'corrupt', '{}')""",
                (operation_id, left_revision),
            )
        connection.commit()
    finally:
        connection.close()


def test_new_database_reports_valid_schema_v3(tmp_path: Path) -> None:
    path = tmp_path / "valid.db"
    with Database(path) as database:
        database.initialize_project("demo")
        report = database.integrity_report()

    assert SCHEMA_VERSION == 3
    assert report["format"] == "weave-database-integrity-v1"
    assert report["schema_version"] == 3
    assert report["valid"] is True
    assert report["issue_count"] == 0
    assert report["issues"] == []

    read_only = inspect_database(path)
    assert read_only["valid"] is True
    assert read_only["path"] == str(path.resolve())


def test_schema_v3_rejects_cross_project_revision_parent(tmp_path: Path) -> None:
    path = tmp_path / "parent.db"
    left_project, _, _, right_revision = _two_projects(path)

    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(
            sqlite3.IntegrityError,
            match="parent1 revision does not belong to project",
        ):
            connection.execute(
                """INSERT INTO revisions(
                       id, project_id, parent1_id, message, author, root_hash
                   ) VALUES (?, ?, ?, 'invalid', 'test', ?)""",
                (str(uuid4()), left_project, right_revision, "0" * 64),
            )
    finally:
        connection.close()


def test_schema_v3_rejects_cross_project_branch_head(tmp_path: Path) -> None:
    path = tmp_path / "branch.db"
    left_project, _, _, right_revision = _two_projects(path)

    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(
            sqlite3.IntegrityError,
            match="branch head revision does not belong to project",
        ):
            connection.execute(
                """INSERT INTO branches(project_id, name, head_revision_id)
                   VALUES (?, 'invalid', ?)""",
                (left_project, right_revision),
            )
    finally:
        connection.close()


def test_schema_v3_rejects_duplicate_operation_sequence(tmp_path: Path) -> None:
    path = tmp_path / "operations.db"
    _, revision, _, _ = _two_projects(path)

    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """INSERT INTO operations(
                   id, revision_id, sequence_number, operation_kind, payload_json
               ) VALUES (?, ?, 0, 'first', '{}')""",
            (str(uuid4()), revision),
        )
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
            connection.execute(
                """INSERT INTO operations(
                       id, revision_id, sequence_number, operation_kind, payload_json
                   ) VALUES (?, ?, 0, 'second', '{}')""",
                (str(uuid4()), revision),
            )
    finally:
        connection.close()


def test_integrity_report_streams_and_bounds_foreign_key_examples(
    tmp_path: Path,
) -> None:
    path = tmp_path / "many-foreign-keys.db"
    with Database(path) as database:
        database.initialize_project("demo")

    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys = OFF")
        for index in range(25):
            connection.execute(
                """INSERT INTO revisions(
                       id, project_id, message, author, root_hash
                   ) VALUES (?, ?, 'invalid', 'test', ?)""",
                (str(uuid4()), f"missing-project-{index}", "0" * 64),
            )
        connection.commit()

        # inspect_connection must not require sqlite3.Row and must retain only a
        # bounded example prefix while reporting the exact violation count.
        report = inspect_connection(connection, path=path.resolve())
    finally:
        connection.close()

    issue = next(item for item in report["issues"] if item["code"] == "FOREIGN_KEY_VIOLATIONS")
    assert issue["count"] == 25
    assert len(issue["examples"]) == 20
    assert issue["examples_truncated"] is True


def test_read_only_check_reports_legacy_corruption(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.db"
    _manufacture_legacy_corruption(path)

    before = path.read_bytes()
    report = inspect_database(path)
    after = path.read_bytes()

    assert after == before
    assert report["schema_version"] == 2
    assert report["valid"] is False
    assert {issue["code"] for issue in report["issues"]} >= {
        "CROSS_PROJECT_PARENT1",
        "CROSS_PROJECT_BRANCH_HEAD",
        "DUPLICATE_OPERATION_SEQUENCE",
    }

    args = build_parser().parse_args(["--db", str(path), "db-check"])
    assert _execute(args) == report


def test_corrupt_legacy_database_is_not_partially_migrated(tmp_path: Path) -> None:
    path = tmp_path / "migration-refusal.db"
    _manufacture_legacy_corruption(path)

    with pytest.raises(
        RuntimeError,
        match="database integrity check failed before schema v3 migration",
    ):
        Database(path)

    connection = sqlite3.connect(path)
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        trigger = connection.execute(
            """SELECT 1 FROM sqlite_master
               WHERE type = 'trigger'
                 AND name = 'revisions_validate_parent_projects_insert'"""
        ).fetchone()
        assert trigger is None
        index = connection.execute(
            """SELECT 1 FROM sqlite_master
               WHERE type = 'index'
                 AND name = 'uq_operations_revision_sequence'"""
        ).fetchone()
        assert index is None
    finally:
        connection.close()
