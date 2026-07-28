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

from .database_integrity import inspect_connection, require_migration_integrity
from .errors import DatabaseBusyError

SCHEMA_VERSION = 3
DEFAULT_DATABASE_BUSY_TIMEOUT_MS = 5_000
MAX_DATABASE_BUSY_TIMEOUT_MS = 2_147_483_647
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
CREATE UNIQUE INDEX IF NOT EXISTS uq_operations_revision_sequence
ON operations(revision_id, sequence_number);

CREATE TRIGGER IF NOT EXISTS revisions_validate_parent_projects_insert
BEFORE INSERT ON revisions
BEGIN
    SELECT RAISE(ABORT, 'parent1 revision does not belong to project')
    WHERE NEW.parent1_id IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM revisions parent
          WHERE parent.id = NEW.parent1_id
            AND parent.project_id = NEW.project_id
      );
    SELECT RAISE(ABORT, 'parent2 revision does not belong to project')
    WHERE NEW.parent2_id IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM revisions parent
          WHERE parent.id = NEW.parent2_id
            AND parent.project_id = NEW.project_id
      );
END;

CREATE TRIGGER IF NOT EXISTS revisions_validate_parent_projects_update
BEFORE UPDATE OF project_id, parent1_id, parent2_id ON revisions
BEGIN
    SELECT RAISE(ABORT, 'parent1 revision does not belong to project')
    WHERE NEW.parent1_id IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM revisions parent
          WHERE parent.id = NEW.parent1_id
            AND parent.project_id = NEW.project_id
      );
    SELECT RAISE(ABORT, 'parent2 revision does not belong to project')
    WHERE NEW.parent2_id IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM revisions parent
          WHERE parent.id = NEW.parent2_id
            AND parent.project_id = NEW.project_id
      );
    SELECT RAISE(ABORT, 'revision project change would orphan a child')
    WHERE EXISTS (
        SELECT 1 FROM revisions child
        WHERE (child.parent1_id = NEW.id OR child.parent2_id = NEW.id)
          AND child.project_id <> NEW.project_id
    );
    SELECT RAISE(ABORT, 'revision project change would orphan a branch')
    WHERE EXISTS (
        SELECT 1 FROM branches branch
        WHERE branch.head_revision_id = NEW.id
          AND branch.project_id <> NEW.project_id
    );
END;

CREATE TRIGGER IF NOT EXISTS branches_validate_project_insert
BEFORE INSERT ON branches
BEGIN
    SELECT RAISE(ABORT, 'branch project does not exist')
    WHERE NOT EXISTS (
        SELECT 1 FROM projects project WHERE project.id = NEW.project_id
    );
    SELECT RAISE(ABORT, 'branch head revision does not belong to project')
    WHERE NOT EXISTS (
        SELECT 1 FROM revisions revision
        WHERE revision.id = NEW.head_revision_id
          AND revision.project_id = NEW.project_id
    );
END;

CREATE TRIGGER IF NOT EXISTS branches_validate_project_update
BEFORE UPDATE OF project_id, head_revision_id ON branches
BEGIN
    SELECT RAISE(ABORT, 'branch project does not exist')
    WHERE NOT EXISTS (
        SELECT 1 FROM projects project WHERE project.id = NEW.project_id
    );
    SELECT RAISE(ABORT, 'branch head revision does not belong to project')
    WHERE NOT EXISTS (
        SELECT 1 FROM revisions revision
        WHERE revision.id = NEW.head_revision_id
          AND revision.project_id = NEW.project_id
    );
END;

PRAGMA user_version = 3;
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


def _is_database_busy_error(error: sqlite3.OperationalError) -> bool:
    code = getattr(error, "sqlite_errorcode", None)
    if isinstance(code, int) and code & 0xFF in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
        return True
    message = str(error).casefold()
    return "database is locked" in message or "database table is locked" in message


class Database:
    def __init__(
        self,
        path: str | Path,
        *,
        busy_timeout_ms: int = DEFAULT_DATABASE_BUSY_TIMEOUT_MS,
    ) -> None:
        if (
            isinstance(busy_timeout_ms, bool)
            or not isinstance(busy_timeout_ms, int)
            or not 0 <= busy_timeout_ms <= MAX_DATABASE_BUSY_TIMEOUT_MS
        ):
            raise ValueError(
                "busy_timeout_ms must be an integer between 0 and "
                f"{MAX_DATABASE_BUSY_TIMEOUT_MS}"
            )
        self.path = Path(path)
        self.busy_timeout_ms = busy_timeout_ms
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(
            self.path,
            timeout=busy_timeout_ms / 1_000,
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
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
        if current_version < SCHEMA_VERSION and self._has_existing_schema():
            try:
                require_migration_integrity(self.connection)
            except Exception:
                self.connection.close()
                raise
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

    def _has_existing_schema(self) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'revisions'"
        ).fetchone()
        return row is not None

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

    def integrity_report(self) -> dict[str, Any]:
        """Return a read-only bounded integrity report for the open database."""

        return inspect_connection(self.connection, path=self.path.resolve())

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
        except sqlite3.OperationalError as exc:
            if self.connection.in_transaction:
                self.connection.rollback()
            if _is_database_busy_error(exc):
                raise DatabaseBusyError(
                    busy_timeout_ms=self.busy_timeout_ms,
                ) from exc
            raise
        except Exception:
            if self.connection.in_transaction:
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
