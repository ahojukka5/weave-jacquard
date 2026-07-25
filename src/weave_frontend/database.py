"""SQLite persistence for immutable revisions, branches, context, and AST snapshots."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import zlib
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

_SNAPSHOT_RAW = b"WJR1"
_SNAPSHOT_ZLIB = b"WJZ1"

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
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    head_revision_id TEXT NOT NULL REFERENCES revisions(id),
    PRIMARY KEY (project_id, name)
);

CREATE TABLE IF NOT EXISTS module_snapshots (
    revision_id TEXT NOT NULL REFERENCES revisions(id),
    qualified_name TEXT NOT NULL,
    ast_blob BLOB NOT NULL,
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
PRAGMA user_version = 2;
"""


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        migrated = self._migrate_module_snapshots()
        if migrated:
            self.connection.execute("VACUUM")
        self.connection.executescript(SCHEMA)

    def _migrate_module_snapshots(self) -> bool:
        row = self.connection.execute(
            "SELECT type FROM sqlite_master WHERE name = 'module_snapshots'"
        ).fetchone()
        if row is None:
            return False
        if row["type"] != "table":
            raise RuntimeError("module_snapshots has an unsupported SQLite object type")

        columns = {
            str(item["name"])
            for item in self.connection.execute("PRAGMA table_info(module_snapshots)")
        }
        if "ast_blob" in columns and "ast_json" not in columns:
            return False
        if "ast_json" not in columns or "ast_blob" in columns:
            raise RuntimeError("module_snapshots has an unsupported schema")

        try:
            self.connection.execute("BEGIN IMMEDIATE")
            legacy_rows = self.connection.execute(
                """SELECT revision_id, qualified_name, ast_json, ast_hash
                   FROM module_snapshots"""
            ).fetchall()
            self.connection.execute(
                "ALTER TABLE module_snapshots RENAME TO module_snapshots_legacy"
            )
            self.connection.execute(
                """CREATE TABLE module_snapshots (
                       revision_id TEXT NOT NULL REFERENCES revisions(id),
                       qualified_name TEXT NOT NULL,
                       ast_blob BLOB NOT NULL,
                       ast_hash TEXT NOT NULL,
                       PRIMARY KEY (revision_id, qualified_name)
                   )"""
            )
            self.connection.executemany(
                """INSERT INTO module_snapshots(
                       revision_id, qualified_name, ast_blob, ast_hash
                   ) VALUES (?, ?, ?, ?)""",
                [
                    (
                        str(item["revision_id"]),
                        str(item["qualified_name"]),
                        self.encode_snapshot(str(item["ast_json"])),
                        str(item["ast_hash"]),
                    )
                    for item in legacy_rows
                ],
            )
            self.connection.execute("DROP TABLE module_snapshots_legacy")
            self.connection.execute("PRAGMA user_version = 2")
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return True

    @staticmethod
    def encode_snapshot(value: str) -> bytes:
        """Encode canonical JSON with a versioned adaptive compression prefix."""

        if not isinstance(value, str):
            raise TypeError("snapshot JSON must be text")
        raw = value.encode("utf-8")
        compressed = zlib.compress(raw, level=3)
        if len(compressed) < len(raw):
            return _SNAPSHOT_ZLIB + compressed
        return _SNAPSHOT_RAW + raw

    @staticmethod
    def decode_snapshot(value: bytes | bytearray | memoryview) -> str:
        """Decode one versioned snapshot payload to canonical JSON text."""

        blob = bytes(value)
        prefix = blob[:4]
        payload = blob[4:]
        if prefix == _SNAPSHOT_ZLIB:
            return zlib.decompress(payload).decode("utf-8")
        if prefix == _SNAPSHOT_RAW:
            return payload.decode("utf-8")
        raise ValueError("unsupported snapshot encoding")

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
