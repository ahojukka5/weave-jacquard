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

SCHEMA_VERSION = 2
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

CREATE TABLE IF NOT EXISTS module_snapshots_compressed (
    revision_id TEXT NOT NULL REFERENCES revisions(id),
    qualified_name TEXT NOT NULL,
    ast_blob BLOB NOT NULL,
    ast_hash TEXT NOT NULL,
    PRIMARY KEY (revision_id, qualified_name)
);

CREATE VIEW IF NOT EXISTS module_snapshots AS
SELECT
    revision_id,
    qualified_name,
    weave_decompress_json(ast_blob) AS ast_json,
    ast_hash
FROM module_snapshots_compressed;

CREATE TRIGGER IF NOT EXISTS module_snapshots_insert
INSTEAD OF INSERT ON module_snapshots
BEGIN
    INSERT INTO module_snapshots_compressed(
        revision_id, qualified_name, ast_blob, ast_hash
    ) VALUES (
        NEW.revision_id,
        NEW.qualified_name,
        weave_compress_json(NEW.ast_json),
        NEW.ast_hash
    );
END;

CREATE TRIGGER IF NOT EXISTS module_snapshots_update
INSTEAD OF UPDATE ON module_snapshots
BEGIN
    UPDATE module_snapshots_compressed
    SET revision_id = NEW.revision_id,
        qualified_name = NEW.qualified_name,
        ast_blob = weave_compress_json(NEW.ast_json),
        ast_hash = NEW.ast_hash
    WHERE revision_id = OLD.revision_id
      AND qualified_name = OLD.qualified_name;
END;

CREATE TRIGGER IF NOT EXISTS module_snapshots_delete
INSTEAD OF DELETE ON module_snapshots
BEGIN
    DELETE FROM module_snapshots_compressed
    WHERE revision_id = OLD.revision_id
      AND qualified_name = OLD.qualified_name;
END;

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


def _compress_json(value: str) -> bytes:
    if not isinstance(value, str):
        raise TypeError("snapshot JSON must be text")
    raw = value.encode("utf-8")
    compressed = zlib.compress(raw, level=3)
    if len(compressed) < len(raw):
        return _SNAPSHOT_ZLIB + compressed
    return _SNAPSHOT_RAW + raw


def _decompress_json(value: bytes | bytearray | memoryview) -> str:
    blob = bytes(value)
    prefix = blob[:4]
    payload = blob[4:]
    if prefix == _SNAPSHOT_ZLIB:
        return zlib.decompress(payload).decode("utf-8")
    if prefix == _SNAPSHOT_RAW:
        return payload.decode("utf-8")
    raise ValueError("unsupported snapshot encoding")


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        current_version = int(
            self.connection.execute("PRAGMA user_version").fetchone()[0]
        )
        if current_version > SCHEMA_VERSION:
            self.connection.close()
            raise RuntimeError(
                "database schema version "
                f"{current_version} is newer than supported version {SCHEMA_VERSION}"
            )
        self.connection.create_function(
            "weave_compress_json",
            1,
            _compress_json,
            deterministic=True,
        )
        self.connection.create_function(
            "weave_decompress_json",
            1,
            _decompress_json,
            deterministic=True,
        )
        migrated = self._migrate_module_snapshots()
        if migrated:
            self.connection.execute("VACUUM")
        self.connection.executescript(SCHEMA)

    def _migrate_module_snapshots(self) -> bool:
        row = self.connection.execute(
            "SELECT type FROM sqlite_master WHERE name = 'module_snapshots'"
        ).fetchone()
        if row is None or row["type"] == "view":
            return False
        if row["type"] != "table":
            raise RuntimeError("module_snapshots has an unsupported SQLite object type")

        columns = {
            str(item["name"])
            for item in self.connection.execute("PRAGMA table_info(module_snapshots)")
        }
        if "ast_json" not in columns:
            raise RuntimeError("module_snapshots has an unsupported schema")

        try:
            self.connection.executescript(
                """
                BEGIN IMMEDIATE;
                ALTER TABLE module_snapshots RENAME TO module_snapshots_legacy;

                CREATE TABLE module_snapshots_compressed (
                    revision_id TEXT NOT NULL REFERENCES revisions(id),
                    qualified_name TEXT NOT NULL,
                    ast_blob BLOB NOT NULL,
                    ast_hash TEXT NOT NULL,
                    PRIMARY KEY (revision_id, qualified_name)
                );

                INSERT INTO module_snapshots_compressed(
                    revision_id, qualified_name, ast_blob, ast_hash
                )
                SELECT
                    revision_id,
                    qualified_name,
                    weave_compress_json(ast_json),
                    ast_hash
                FROM module_snapshots_legacy;

                DROP TABLE module_snapshots_legacy;

                CREATE VIEW module_snapshots AS
                SELECT
                    revision_id,
                    qualified_name,
                    weave_decompress_json(ast_blob) AS ast_json,
                    ast_hash
                FROM module_snapshots_compressed;

                CREATE TRIGGER module_snapshots_insert
                INSTEAD OF INSERT ON module_snapshots
                BEGIN
                    INSERT INTO module_snapshots_compressed(
                        revision_id, qualified_name, ast_blob, ast_hash
                    ) VALUES (
                        NEW.revision_id,
                        NEW.qualified_name,
                        weave_compress_json(NEW.ast_json),
                        NEW.ast_hash
                    );
                END;

                CREATE TRIGGER module_snapshots_update
                INSTEAD OF UPDATE ON module_snapshots
                BEGIN
                    UPDATE module_snapshots_compressed
                    SET revision_id = NEW.revision_id,
                        qualified_name = NEW.qualified_name,
                        ast_blob = weave_compress_json(NEW.ast_json),
                        ast_hash = NEW.ast_hash
                    WHERE revision_id = OLD.revision_id
                      AND qualified_name = OLD.qualified_name;
                END;

                CREATE TRIGGER module_snapshots_delete
                INSTEAD OF DELETE ON module_snapshots
                BEGIN
                    DELETE FROM module_snapshots_compressed
                    WHERE revision_id = OLD.revision_id
                      AND qualified_name = OLD.qualified_name;
                END;

                PRAGMA user_version = 2;
                COMMIT;
                """
            )
        except Exception:
            self.connection.rollback()
            raise
        return True

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
