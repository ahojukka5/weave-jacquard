from __future__ import annotations

import json
import sqlite3
from uuid import uuid4

import pytest

from weave_frontend import SExpressionWorkspace
from weave_frontend.database import Database
from weave_frontend.sexpr import make_atom, make_form


def _large_program_source() -> str:
    return (
        '(program (name "compressed") (version "0.1") '
        '(entry main (params) (returns i32) '
        '(do (let payload ptr (const_string_ptr "'
        + ("repeated-value-" * 2000)
        + '")) (return (const_i32 42)))))'
    )


def _legacy_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE revisions (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id),
            parent1_id TEXT REFERENCES revisions(id),
            parent2_id TEXT REFERENCES revisions(id),
            message TEXT NOT NULL,
            author TEXT NOT NULL,
            root_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE branches (
            project_id TEXT NOT NULL,
            name TEXT NOT NULL,
            head_revision_id TEXT NOT NULL REFERENCES revisions(id),
            PRIMARY KEY (project_id, name)
        );
        CREATE TABLE module_snapshots (
            revision_id TEXT NOT NULL REFERENCES revisions(id),
            qualified_name TEXT NOT NULL,
            ast_json TEXT NOT NULL,
            ast_hash TEXT NOT NULL,
            PRIMARY KEY (revision_id, qualified_name)
        );
        CREATE TABLE operations (
            id TEXT PRIMARY KEY,
            revision_id TEXT NOT NULL REFERENCES revisions(id),
            sequence_number INTEGER NOT NULL,
            operation_kind TEXT NOT NULL,
            target TEXT,
            payload_json TEXT NOT NULL
        );
        CREATE TABLE documents (
            id TEXT PRIMARY KEY,
            scope_kind TEXT NOT NULL,
            scope_name TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            content_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE revision_documents (
            revision_id TEXT NOT NULL REFERENCES revisions(id),
            document_id TEXT NOT NULL REFERENCES documents(id),
            PRIMARY KEY (revision_id, document_id)
        );
        """
    )


def test_new_snapshots_are_transparently_compressed_and_reopen(tmp_path):
    path = tmp_path / "compressed.db"
    source = _large_program_source()

    with SExpressionWorkspace(path) as workspace:
        workspace.initialize("demo")
        workspace.import_program("demo", "main", "main.weave", source)
        assert workspace.render("demo", "main", "main.weave") == source

        object_type = workspace.db.connection.execute(
            "SELECT type FROM sqlite_master WHERE name = 'module_snapshots'"
        ).fetchone()[0]
        raw_size, stored_size, prefix = workspace.db.connection.execute(
            """SELECT length(ast_json), length(ast_blob), substr(ast_blob, 1, 4)
               FROM module_snapshots
               JOIN module_snapshots_compressed USING (revision_id, qualified_name)"""
        ).fetchone()
        assert object_type == "view"
        assert bytes(prefix) == b"WJZ1"
        assert stored_size < raw_size // 4

    with SExpressionWorkspace(path) as reopened:
        assert reopened.render("demo", "main", "main.weave") == source


def test_legacy_snapshot_table_migrates_without_changing_history(tmp_path):
    path = tmp_path / "legacy.db"
    project_id = str(uuid4())
    revision_id = str(uuid4())
    root = make_form("program")
    name = make_form("name")
    name["children"].append(make_atom("string", "legacy"))
    root["children"].append(name)
    ast_json = Database.canonical_json(root)

    connection = sqlite3.connect(path)
    _legacy_schema(connection)
    connection.execute(
        "INSERT INTO projects(id, name) VALUES (?, ?)",
        (project_id, "legacy"),
    )
    connection.execute(
        """INSERT INTO revisions(id, project_id, message, author, root_hash)
           VALUES (?, ?, 'legacy revision', 'test', ?)""",
        (revision_id, project_id, Database.hash_value({"main.weave": root})),
    )
    connection.execute(
        "INSERT INTO branches(project_id, name, head_revision_id) VALUES (?, 'main', ?)",
        (project_id, revision_id),
    )
    connection.execute(
        """INSERT INTO module_snapshots(revision_id, qualified_name, ast_json, ast_hash)
           VALUES (?, 'main.weave', ?, ?)""",
        (revision_id, ast_json, Database.hash_value(root)),
    )
    connection.commit()
    connection.close()

    with SExpressionWorkspace(path) as workspace:
        assert workspace.render("legacy", "main", "main.weave") == '(program (name "legacy"))'
        row = workspace.db.connection.execute(
            "SELECT type FROM sqlite_master WHERE name = 'module_snapshots'"
        ).fetchone()
        assert row[0] == "view"
        assert workspace.db.connection.execute(
            "SELECT count(*) FROM module_snapshots_compressed"
        ).fetchone()[0] == 1
        assert workspace.db.connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE name = 'module_snapshots_legacy'"
        ).fetchone()[0] == 0


def test_snapshot_view_preserves_transactional_insert_update_delete(tmp_path):
    with Database(tmp_path / "view.db") as database:
        project_id, revision_id = database.initialize_project("demo")
        ast = json.dumps({"payload": "x" * 1000})

        with database.transaction() as connection:
            connection.execute(
                """INSERT INTO module_snapshots(revision_id, qualified_name, ast_json, ast_hash)
                   VALUES (?, 'main', ?, 'hash-1')""",
                (revision_id, ast),
            )
        assert database.connection.execute(
            "SELECT ast_json FROM module_snapshots"
        ).fetchone()[0] == ast

        with database.transaction() as connection:
            connection.execute(
                """UPDATE module_snapshots SET ast_json = ?, ast_hash = 'hash-2'
                   WHERE revision_id = ? AND qualified_name = 'main'""",
                (ast.replace("x", "y"), revision_id),
            )
        assert "y" * 100 in database.connection.execute(
            "SELECT ast_json FROM module_snapshots"
        ).fetchone()[0]

        with pytest.raises(RuntimeError):
            with database.transaction() as connection:
                connection.execute(
                    "DELETE FROM module_snapshots WHERE revision_id = ?",
                    (revision_id,),
                )
                raise RuntimeError("rollback")
        assert database.connection.execute(
            "SELECT count(*) FROM module_snapshots"
        ).fetchone()[0] == 1

        with database.transaction() as connection:
            connection.execute(
                "DELETE FROM module_snapshots WHERE revision_id = ?",
                (revision_id,),
            )
        assert database.connection.execute(
            "SELECT count(*) FROM module_snapshots"
        ).fetchone()[0] == 0
