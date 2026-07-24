"""SQLite persistence for immutable revisions, branches, context, and AST snapshots."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS revisions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    parent1_id TEXT REFERENCES revisions(id),
    parent2_id TEXT REFERENCES revisions(id),
    message TEXT NOT NULL,
    author TEXT NOT NULL,
    root_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS branches (
    project_id TEXT NOT NULL REFERENCES projects(id),
    name TEXT NOT NULL,
    head_revision_id TEXT NOT NULL REFERENCES revisions(id),
    PRIMARY KEY (project_id, name)
);

CREATE TABLE IF NOT EXISTS module_snapshots (
    revision_id TEXT NOT NULL REFERENCES revisions(id),
    qualified_name TEXT NOT NULL,
    ast_json TEXT NOT NULL,
    ast_hash TEXT NOT NULL,
    PRIMARY KEY (revision_id, qualified_name)
);

CREATE TABLE IF NOT EXISTS operations (
    id TEXT PRIMARY KEY,
    revision_id TEXT NOT NULL REFERENCES revisions(id),
    sequence_number INTEGER NOT NULL,
    operation_kind TEXT NOT NULL,
    target TEXT,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    scope_kind TEXT NOT NULL,
    scope_name TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS revision_documents (
    revision_id TEXT NOT NULL REFERENCES revisions(id),
    document_id TEXT NOT NULL REFERENCES documents(id),
    PRIMARY KEY (revision_id, document_id)
);

CREATE INDEX IF NOT EXISTS idx_documents_scope ON documents(scope_kind, scope_name);
CREATE INDEX IF NOT EXISTS idx_operations_revision ON operations(revision_id, sequence_number);
"""


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterable[sqlite3.Connection]:
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            yield self.connection
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    @staticmethod
    def canonical_json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @classmethod
    def hash_value(cls, value: Any) -> str:
        return hashlib.sha256(cls.canonical_json(value).encode()).hexdigest()

    def initialize_project(self, name: str, *, author: str = "system") -> tuple[str, str]:
        project_id = str(uuid4())
        revision_id = str(uuid4())
        with self.transaction() as conn:
            conn.execute("INSERT INTO projects(id, name) VALUES (?, ?)", (project_id, name))
            conn.execute(
                """INSERT INTO revisions(id, project_id, message, author, root_hash)
                   VALUES (?, ?, ?, ?, ?)""",
                (revision_id, project_id, "initialize project", author, self.hash_value({})),
            )
            conn.execute(
                "INSERT INTO branches(project_id, name, head_revision_id) VALUES (?, 'main', ?)",
                (project_id, revision_id),
            )
        return project_id, revision_id
