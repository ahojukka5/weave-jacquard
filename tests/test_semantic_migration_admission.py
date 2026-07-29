from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from weave_frontend.database import Database
from weave_frontend.sexpr import make_form
from weave_frontend.snapshot_codec import canonical_json, hash_value


def _legacy_database(path: Path, *, ast_hash: str) -> None:
    project_id = str(uuid4())
    revision_id = str(uuid4())
    tree = make_form("program")
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
        PRAGMA user_version = 2;
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
    connection.execute(
        "INSERT INTO projects(id, name) VALUES (?, 'legacy')",
        (project_id,),
    )
    connection.execute(
        """INSERT INTO revisions(id, project_id, message, author, root_hash)
           VALUES (?, ?, 'legacy', 'test', ?)""",
        (revision_id, project_id, hash_value({"main.weave": tree})),
    )
    connection.execute(
        """INSERT INTO branches(project_id, name, head_revision_id)
           VALUES (?, 'main', ?)""",
        (project_id, revision_id),
    )
    connection.execute(
        """INSERT INTO module_snapshots(
               revision_id, qualified_name, ast_json, ast_hash
           ) VALUES (?, 'main.weave', ?, ?)""",
        (revision_id, canonical_json(tree), ast_hash),
    )
    connection.commit()
    connection.close()


def test_legacy_ast_hash_corruption_blocks_schema_migration(tmp_path: Path) -> None:
    path = tmp_path / "legacy-corrupt.db"
    _legacy_database(path, ast_hash="0" * 64)

    with pytest.raises(
        RuntimeError,
        match="SNAPSHOT_AST_HASH_MISMATCH",
    ):
        Database(path)

    connection = sqlite3.connect(path)
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert connection.execute(
            """SELECT type FROM sqlite_master
               WHERE name = 'module_snapshots'"""
        ).fetchone()[0] == "table"
        assert connection.execute(
            """SELECT 1 FROM sqlite_master
               WHERE name = 'module_snapshots_compressed'"""
        ).fetchone() is None
    finally:
        connection.close()
