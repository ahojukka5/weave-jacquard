"""Verified online SQLite backup storage and non-destructive offline restore."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from .compiler_artifacts import CompilerArtifactMixin
from .database_integrity import inspect_database
from .errors import ArtifactIntegrityError, NotFoundError, ValidationError
from .retained_artifact_io import (
    RetainedArtifactReadError,
    read_bounded_regular_json,
)

DATABASE_BACKUP_FORMAT = "weave-database-backup-v1"
DATABASE_BACKUP_KEY_FORMAT = "weave-database-backup-key-v1"
DATABASE_RESTORE_FORMAT = "weave-database-restore-v1"
DATABASE_BACKUP_ID_LENGTH = 64
_HEXADECIMAL = "0123456789abcdef"
MAX_DATABASE_BACKUP_MANIFEST_BYTES = 1024 * 1024
DEFAULT_DATABASE_BACKUP_TIMEOUT_SECONDS = 300
MAX_DATABASE_BACKUP_TIMEOUT_SECONDS = 3600
DATABASE_BACKUP_PAGES_PER_STEP = 256


class DatabaseBackupService(CompilerArtifactMixin):
    """Create, verify, inspect, and restore immutable single-file SQLite backups."""

    def __init__(
        self,
        database: Any,
        *,
        backup_root: str | Path | None = None,
    ) -> None:
        self.database = database
        configured = backup_root or os.environ.get("WEAVE_DATABASE_BACKUP_ROOT")
        if configured is None:
            configured = database.path.parent / ".weave-database-backups"
        self.backup_root = Path(configured).resolve()
        self.backup_root.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        *,
        timeout_seconds: int = DEFAULT_DATABASE_BACKUP_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        """Create one consistent online backup and publish verified evidence."""

        self._validate_timeout(timeout_seconds)
        connection = self.database.connection
        if connection.in_transaction:
            raise ValidationError(
                "DATABASE_BACKUP_TRANSACTION_ACTIVE",
                "database backup requires no active transaction on the source connection",
            )

        source = {
            **self._connection_identity(connection),
            "location_id": self._location_id(self.database.path),
        }
        with tempfile.TemporaryDirectory(
            prefix=".database-backup-",
            dir=self.backup_root,
        ) as temporary:
            temporary_directory = Path(temporary)
            database_path = temporary_directory / "database.sqlite3"
            self._copy_online(
                connection,
                database_path,
                timeout_seconds=timeout_seconds,
            )
            integrity = self._normalized_integrity(database_path)
            if integrity.get("valid") is not True:
                raise ValidationError(
                    "DATABASE_BACKUP_INTEGRITY_FAILED",
                    "online database backup did not pass integrity verification",
                )
            artifact_identity = self._database_file_identity(database_path)
            backup_database = self._database_identity(database_path)
            key = self._backup_key(
                source=source,
                backup_database=backup_database,
                artifact_identity=artifact_identity,
            )
            backup_id = self._hash_json(key)
            manifest = {
                "format": DATABASE_BACKUP_FORMAT,
                "key_format": DATABASE_BACKUP_KEY_FORMAT,
                "backup_id": backup_id,
                "cached": False,
                "source": source,
                "backup_database": backup_database,
                "integrity": integrity,
                "artifacts": {"database": "database.sqlite3"},
                "artifact_bytes": {"database": artifact_identity["bytes"]},
                "artifact_sha256": {"database": artifact_identity["sha256"]},
                "backup_key": key,
            }
            manifest_path = temporary_directory / "backup-manifest.json"
            self._write_json(manifest_path, manifest)
            self._verify_manifest(
                self._read_manifest(manifest_path),
                temporary_directory,
                expected_id=backup_id,
            )
            self._fsync_file(database_path)
            self._fsync_file(manifest_path)
            self._fsync_directory(temporary_directory)

            final_directory = self._backup_directory(
                backup_id,
                require_exists=False,
            )
            with self._publication_lock(final_directory):
                if os.path.lexists(final_directory):
                    existing = self.get(backup_id)
                    existing["cached"] = True
                    return existing
                os.replace(temporary_directory, final_directory)
                self._fsync_directory(self.backup_root)
        return self.get(backup_id)

    def get(self, backup_id: str) -> dict[str, Any]:
        """Read and reverify one immutable backup manifest and database file."""

        directory = self._backup_directory(backup_id)
        manifest_path = directory / "backup-manifest.json"
        manifest = self._read_manifest(manifest_path)
        self._verify_manifest(manifest, directory, expected_id=backup_id)
        result = dict(manifest)
        result["manifest_sha256"] = self._stable_file_identity(manifest_path)["sha256"]
        return result

    def restore(
        self,
        backup_id: str,
        destination: str | Path,
    ) -> dict[str, Any]:
        """Restore a verified backup atomically to one new offline destination."""

        backup = self.get(backup_id)
        backup_directory = self._backup_directory(backup_id)
        source = backup_directory / backup["artifacts"]["database"]
        destination_path = self._restore_destination(destination)
        parent = destination_path.parent
        parent.mkdir(parents=True, exist_ok=True)
        self._require_restore_destination_absent(destination_path)

        temporary = parent / f".{destination_path.name}.restore-{uuid.uuid4().hex}"
        try:
            copied = self._copy_regular_file(source, temporary)
            expected_hash = backup["artifact_sha256"]["database"]
            expected_bytes = backup["artifact_bytes"]["database"]
            if copied["sha256"] != expected_hash or copied["bytes"] != expected_bytes:
                raise ArtifactIntegrityError(
                    "restored database bytes do not match verified backup evidence"
                )
            integrity = self._normalized_integrity(temporary)
            if integrity != backup["integrity"]:
                raise ArtifactIntegrityError(
                    "restored database integrity evidence differs from the backup"
                )
            self._fsync_file(temporary)
            self._require_restore_destination_absent(destination_path)
            try:
                os.link(temporary, destination_path, follow_symlinks=False)
            except FileExistsError as exc:
                raise ValidationError(
                    "DATABASE_RESTORE_DESTINATION_EXISTS",
                    "restore destination appeared during atomic publication",
                ) from exc
            os.unlink(temporary)
            self._fsync_directory(parent)
        finally:
            if os.path.lexists(temporary):
                self._remove_path(temporary)

        final_identity = self._database_file_identity(destination_path)
        if (
            final_identity["sha256"] != backup["artifact_sha256"]["database"]
            or final_identity["bytes"] != backup["artifact_bytes"]["database"]
        ):
            raise ArtifactIntegrityError(
                "restored database changed after atomic publication"
            )
        return {
            "format": DATABASE_RESTORE_FORMAT,
            "backup_id": backup_id,
            "destination": str(destination_path),
            "database_bytes": final_identity["bytes"],
            "database_sha256": final_identity["sha256"],
            "schema_version": backup["backup_database"]["schema_version"],
            "integrity_valid": True,
            "replaced_existing": False,
        }

    def _copy_online(
        self,
        source: sqlite3.Connection,
        destination_path: Path,
        *,
        timeout_seconds: int,
    ) -> None:
        deadline = time.monotonic() + timeout_seconds

        def progress(_status: int, _remaining: int, _total: int) -> None:
            if time.monotonic() > deadline:
                raise ValidationError(
                    "DATABASE_BACKUP_TIMEOUT",
                    f"database backup exceeded {timeout_seconds} seconds",
                )

        destination = sqlite3.connect(destination_path)
        try:
            try:
                source.backup(
                    destination,
                    pages=DATABASE_BACKUP_PAGES_PER_STEP,
                    progress=progress,
                    sleep=0.05,
                )
                destination.execute("PRAGMA journal_mode = DELETE")
                destination.commit()
            except ValidationError:
                raise
            except sqlite3.Error as exc:
                raise ValidationError(
                    "DATABASE_BACKUP_FAILED",
                    "SQLite online backup failed",
                ) from exc
        finally:
            destination.close()
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = Path(str(destination_path) + suffix)
            if os.path.lexists(sidecar):
                raise ValidationError(
                    "DATABASE_BACKUP_SIDECAR_RETAINED",
                    "database backup did not produce one self-contained SQLite file",
                )

    def _verify_manifest(
        self,
        manifest: dict[str, Any],
        directory: Path,
        *,
        expected_id: str,
    ) -> None:
        if manifest.get("format") != DATABASE_BACKUP_FORMAT:
            raise ArtifactIntegrityError("database backup manifest format is invalid")
        if manifest.get("key_format") != DATABASE_BACKUP_KEY_FORMAT:
            raise ArtifactIntegrityError("database backup key format is invalid")
        if manifest.get("backup_id") != expected_id:
            raise ArtifactIntegrityError("database backup manifest identity is invalid")
        if manifest.get("artifacts") != {"database": "database.sqlite3"}:
            raise ArtifactIntegrityError("database backup artifact path is invalid")
        database_path = directory / "database.sqlite3"
        identity = self._database_file_identity(database_path)
        if manifest.get("artifact_bytes") != {"database": identity["bytes"]}:
            raise ArtifactIntegrityError("database backup byte count is invalid")
        if manifest.get("artifact_sha256") != {"database": identity["sha256"]}:
            raise ArtifactIntegrityError("database backup checksum is invalid")

        database_identity = self._database_identity(database_path)
        if manifest.get("backup_database") != database_identity:
            raise ArtifactIntegrityError("database backup SQLite identity is invalid")
        try:
            integrity = self._normalized_integrity(database_path)
        except ValidationError as exc:
            raise ArtifactIntegrityError(
                "database backup integrity inspection failed"
            ) from exc
        if integrity.get("valid") is not True or manifest.get("integrity") != integrity:
            raise ArtifactIntegrityError("database backup integrity evidence is invalid")

        source = manifest.get("source")
        if not self._valid_database_identity(source, require_location=True):
            raise ArtifactIntegrityError("database backup source evidence is invalid")
        key = self._backup_key(
            source=source,
            backup_database=database_identity,
            artifact_identity=identity,
        )
        if manifest.get("backup_key") != key or self._hash_json(key) != expected_id:
            raise ArtifactIntegrityError("database backup content-derived key is invalid")

    @staticmethod
    def _backup_key(
        *,
        source: dict[str, Any],
        backup_database: dict[str, Any],
        artifact_identity: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "format": DATABASE_BACKUP_KEY_FORMAT,
            "source": source,
            "backup_database": backup_database,
            "database_sha256": artifact_identity["sha256"],
            "database_bytes": artifact_identity["bytes"],
        }

    def _backup_directory(
        self,
        backup_id: str,
        *,
        require_exists: bool = True,
    ) -> Path:
        self._validate_backup_id(backup_id)
        directory = self.backup_root / backup_id
        if require_exists:
            try:
                metadata = directory.lstat()
            except OSError as exc:
                raise NotFoundError(f"database backup {backup_id!r} not found") from exc
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise ArtifactIntegrityError(
                    "database backup directory must be a non-symlink directory"
                )
        return directory

    def _restore_destination(self, destination: str | Path) -> Path:
        raw = Path(destination).expanduser()
        if raw.name in {"", ".", ".."}:
            raise ValidationError(
                "INVALID_DATABASE_RESTORE_DESTINATION",
                "restore destination must identify a database file",
            )
        parent = raw.parent.resolve()
        destination_path = parent / raw.name
        try:
            destination_path.relative_to(self.backup_root)
        except ValueError:
            return destination_path
        raise ValidationError(
            "INVALID_DATABASE_RESTORE_DESTINATION",
            "restore destination cannot be inside the backup store",
        )

    @staticmethod
    def _require_restore_destination_absent(destination: Path) -> None:
        candidates = [
            destination,
            Path(str(destination) + "-wal"),
            Path(str(destination) + "-shm"),
            Path(str(destination) + "-journal"),
        ]
        if any(os.path.lexists(path) for path in candidates):
            raise ValidationError(
                "DATABASE_RESTORE_DESTINATION_EXISTS",
                "restore destination or SQLite sidecar already exists",
            )

    @staticmethod
    def _copy_regular_file(source: Path, destination: Path) -> dict[str, Any]:
        source_flags = os.O_RDONLY
        if hasattr(os, "O_CLOEXEC"):
            source_flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            source_flags |= os.O_NOFOLLOW
        source_descriptor = os.open(source, source_flags)
        destination_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_CLOEXEC"):
            destination_flags |= os.O_CLOEXEC
        try:
            source_before = os.fstat(source_descriptor)
            if not stat.S_ISREG(source_before.st_mode):
                raise ArtifactIntegrityError("database backup artifact is not regular")
            destination_descriptor = os.open(destination, destination_flags, 0o600)
            digest = hashlib.sha256()
            copied = 0
            try:
                while chunk := os.read(source_descriptor, 1024 * 1024):
                    digest.update(chunk)
                    copied += len(chunk)
                    view = memoryview(chunk)
                    while view:
                        written = os.write(destination_descriptor, view)
                        if written <= 0:
                            raise OSError("database restore write made no progress")
                        view = view[written:]
                os.fsync(destination_descriptor)
            finally:
                os.close(destination_descriptor)
            source_after = os.fstat(source_descriptor)
            if (
                source_before.st_dev,
                source_before.st_ino,
                source_before.st_size,
                source_before.st_mtime_ns,
            ) != (
                source_after.st_dev,
                source_after.st_ino,
                source_after.st_size,
                source_after.st_mtime_ns,
            ):
                raise ArtifactIntegrityError(
                    "database backup artifact changed during restore"
                )
            return {"bytes": copied, "sha256": digest.hexdigest()}
        finally:
            os.close(source_descriptor)

    @classmethod
    def _database_file_identity(cls, path: Path) -> dict[str, Any]:
        return cls._stable_file_identity(path)

    @staticmethod
    def _stable_file_identity(path: Path) -> dict[str, Any]:
        flags = os.O_RDONLY
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise ArtifactIntegrityError("cannot open database backup artifact") from exc
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise ArtifactIntegrityError(
                    "database backup artifact must be a regular file"
                )
            digest = hashlib.sha256()
            total = 0
            while chunk := os.read(descriptor, 1024 * 1024):
                digest.update(chunk)
                total += len(chunk)
            after = os.fstat(descriptor)
            if (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ):
                raise ArtifactIntegrityError(
                    "database backup artifact changed while hashing"
                )
            if total != before.st_size:
                raise ArtifactIntegrityError(
                    "database backup artifact size changed while hashing"
                )
            return {"bytes": total, "sha256": digest.hexdigest()}
        finally:
            os.close(descriptor)

    @staticmethod
    def _connection_identity(connection: sqlite3.Connection) -> dict[str, Any]:
        return {
            "schema_version": int(
                connection.execute("PRAGMA user_version").fetchone()[0]
            ),
            "page_size": int(connection.execute("PRAGMA page_size").fetchone()[0]),
            "page_count": int(connection.execute("PRAGMA page_count").fetchone()[0]),
            "journal_mode": str(
                connection.execute("PRAGMA journal_mode").fetchone()[0]
            ).lower(),
            "sqlite_version": sqlite3.sqlite_version,
        }

    @classmethod
    def _database_identity(cls, path: Path) -> dict[str, Any]:
        try:
            uri = path.resolve().as_uri() + "?mode=ro"
            connection = sqlite3.connect(uri, uri=True)
        except (OSError, sqlite3.Error) as exc:
            raise ArtifactIntegrityError(
                "cannot open database backup for SQLite identity inspection"
            ) from exc
        try:
            identity = cls._connection_identity(connection)
        except sqlite3.Error as exc:
            raise ArtifactIntegrityError(
                "cannot inspect database backup SQLite identity"
            ) from exc
        finally:
            connection.close()
        if not cls._valid_database_identity(identity, require_location=False):
            raise ArtifactIntegrityError("database backup SQLite identity is invalid")
        return identity

    @staticmethod
    def _valid_database_identity(value: Any, *, require_location: bool) -> bool:
        if not isinstance(value, dict):
            return False
        required = {
            "schema_version",
            "page_size",
            "page_count",
            "journal_mode",
            "sqlite_version",
        }
        if require_location:
            required.add("location_id")
        if set(value) != required:
            return False
        integer_fields = ("schema_version", "page_size", "page_count")
        if any(
            isinstance(value[field], bool)
            or not isinstance(value[field], int)
            or value[field] < 0
            for field in integer_fields
        ):
            return False
        if value["page_size"] <= 0:
            return False
        if not isinstance(value["journal_mode"], str) or not value["journal_mode"]:
            return False
        if not isinstance(value["sqlite_version"], str) or not value["sqlite_version"]:
            return False
        if require_location:
            location = value["location_id"]
            if (
                not isinstance(location, str)
                or len(location) != 64
                or any(character not in _HEXADECIMAL for character in location)
            ):
                return False
        return True

    @staticmethod
    def _normalized_integrity(path: Path) -> dict[str, Any]:
        report = inspect_database(path)
        return {**report, "path": None}

    @staticmethod
    def _read_manifest(path: Path) -> dict[str, Any]:
        try:
            value = read_bounded_regular_json(
                path,
                max_bytes=MAX_DATABASE_BACKUP_MANIFEST_BYTES,
            )
        except RetainedArtifactReadError as exc:
            raise ArtifactIntegrityError(
                f"cannot read database backup manifest: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise ArtifactIntegrityError(
                "database backup manifest root must be an object"
            )
        return value

    @staticmethod
    def _validate_backup_id(backup_id: Any) -> None:
        if (
            not isinstance(backup_id, str)
            or len(backup_id) != DATABASE_BACKUP_ID_LENGTH
            or any(character not in _HEXADECIMAL for character in backup_id)
        ):
            raise ValidationError(
                "INVALID_DATABASE_BACKUP_ID",
                "backup_id must be 64 lowercase hexadecimal characters",
            )

    @staticmethod
    def _validate_timeout(timeout_seconds: Any) -> None:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int)
            or not 1 <= timeout_seconds <= MAX_DATABASE_BACKUP_TIMEOUT_SECONDS
        ):
            raise ValidationError(
                "INVALID_DATABASE_BACKUP_TIMEOUT",
                "timeout_seconds must be between 1 and "
                f"{MAX_DATABASE_BACKUP_TIMEOUT_SECONDS}",
            )

    @staticmethod
    def _location_id(path: Path) -> str:
        encoded = b"weave-database-location-v1\0" + str(path.resolve()).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _hash_json(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _fsync_file(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        descriptor = os.open(path, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


__all__ = [
    "DATABASE_BACKUP_FORMAT",
    "DATABASE_BACKUP_KEY_FORMAT",
    "DATABASE_RESTORE_FORMAT",
    "DEFAULT_DATABASE_BACKUP_TIMEOUT_SECONDS",
    "MAX_DATABASE_BACKUP_MANIFEST_BYTES",
    "MAX_DATABASE_BACKUP_TIMEOUT_SECONDS",
    "DatabaseBackupService",
]
