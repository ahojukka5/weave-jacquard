"""Durable no-follow filesystem primitives for artifact quarantine."""

from __future__ import annotations

import fcntl
import json
import os
import stat
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ...errors import ValidationError
from ...retained_artifact_io import (
    RetainedArtifactReadError,
    read_bounded_regular_json,
)

MAX_ARTIFACT_QUARANTINE_METADATA_BYTES = 4 * 1024 * 1024


class ArtifactQuarantineIO:
    """Publish durable quarantine metadata without following filesystem links."""

    def __init__(self, reconciliation: Any) -> None:
        self.reconciliation = reconciliation
        database_path = Path(reconciliation.database.path).expanduser().resolve()
        self.control_root = database_path.parent / ".weave-artifact-quarantine"
        self._prepare_control_root()

    def journal_path(self, quarantine_id: str) -> Path:
        return self.control_root / f"{quarantine_id}.json"

    def control_lock_path(self, quarantine_id: str) -> Path:
        return self.control_root / f".{quarantine_id}.lock"

    def read_optional_metadata(self, path: Path) -> dict[str, Any] | None:
        if not os.path.lexists(path):
            return None
        return self.read_metadata(path)

    def read_metadata(self, path: Path) -> dict[str, Any]:
        try:
            value = read_bounded_regular_json(
                path,
                max_bytes=MAX_ARTIFACT_QUARANTINE_METADATA_BYTES,
            )
        except RetainedArtifactReadError as exc:
            self.metadata_error("cannot read quarantine metadata", exc)
        if not isinstance(value, dict):
            self.metadata_error("quarantine metadata root must be an object")
        return value

    def write_metadata(self, path: Path, value: Mapping[str, Any]) -> None:
        try:
            payload = (
                json.dumps(
                    value,
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=False,
                    allow_nan=False,
                )
                + "\n"
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            self.metadata_error("quarantine metadata is not canonical JSON", exc)
        if len(payload) > MAX_ARTIFACT_QUARANTINE_METADATA_BYTES:
            self.metadata_error("quarantine metadata exceeds the bounded size")

        existing = self.read_optional_metadata(path)
        if existing is not None:
            if existing != dict(value):
                self.metadata_error("existing quarantine metadata conflicts")
            return

        temporary = path.parent / f".{path.name}.tmp"
        self._discard_regular_temporary(temporary)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor: int | None = None
        try:
            descriptor = os.open(temporary, flags, 0o600)
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("quarantine metadata write made no progress")
                view = view[written:]
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            if os.path.lexists(path):
                existing = self.read_metadata(path)
                if existing != dict(value):
                    self.metadata_error("existing quarantine metadata conflicts")
                return
            os.replace(temporary, path)
            self.fsync_directory(path.parent)
        except ValidationError:
            raise
        except OSError as exc:
            self.metadata_error("cannot publish quarantine metadata", exc)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            self._discard_regular_temporary(temporary)

    def ensure_staging(self, path: Path) -> None:
        if os.path.lexists(path):
            self.require_directory(path)
            return
        try:
            path.mkdir(mode=0o700)
            self.fsync_directory(path.parent)
        except FileExistsError:
            self.require_directory(path)
        except OSError as exc:
            self.metadata_error("cannot create quarantine staging directory", exc)

    @contextmanager
    def lock(self, path: Path) -> Iterator[None]:
        """Hold one non-symlink regular advisory lock file."""

        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags, 0o600)
        except OSError as exc:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_LOCK_UNAVAILABLE",
                "cannot open a quarantine publication lock",
            ) from exc
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise ValidationError(
                    "ARTIFACT_QUARANTINE_LOCK_INVALID",
                    "quarantine publication lock must be a regular file",
                )
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    @staticmethod
    def require_directory(path: Path) -> None:
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_CAPSULE_UNAVAILABLE",
                "quarantine capsule directory is unavailable",
            ) from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ValidationError(
                "ARTIFACT_QUARANTINE_CAPSULE_INVALID",
                "quarantine capsule must be a non-symlink directory",
            )

    @staticmethod
    def fsync_directory(path: Path) -> None:
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_SYNC_FAILED",
                "cannot open a quarantine directory for synchronization",
            ) from exc
        try:
            os.fsync(descriptor)
        except OSError as exc:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_SYNC_FAILED",
                "cannot synchronize quarantine directory metadata",
            ) from exc
        finally:
            os.close(descriptor)

    @staticmethod
    def metadata_error(message: str, exc: Exception | None = None) -> None:
        error = ValidationError("ARTIFACT_QUARANTINE_METADATA_INVALID", message)
        if exc is None:
            raise error
        raise error from exc

    def _prepare_control_root(self) -> None:
        families = self.reconciliation.inventory.families
        for family in families:
            root = family.root
            if self._overlaps(self.control_root, root):
                raise ValidationError(
                    "ARTIFACT_QUARANTINE_CONTROL_ROOT_CONFLICT",
                    "quarantine control storage overlaps a retained artifact root",
                )
        try:
            created = not os.path.lexists(self.control_root)
            self.control_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.require_directory(self.control_root)
            if created:
                self.fsync_directory(self.control_root.parent)
        except ValidationError:
            raise
        except OSError as exc:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_CONTROL_ROOT_UNAVAILABLE",
                "cannot prepare quarantine control storage",
            ) from exc

    @staticmethod
    def _overlaps(left: Path, right: Path) -> bool:
        try:
            left.relative_to(right)
            return True
        except ValueError:
            pass
        try:
            right.relative_to(left)
            return True
        except ValueError:
            return False

    @staticmethod
    def _discard_regular_temporary(path: Path) -> None:
        if not os.path.lexists(path):
            return
        try:
            metadata = path.lstat()
            if stat.S_ISREG(metadata.st_mode):
                path.unlink()
        except OSError:
            pass


__all__ = [
    "MAX_ARTIFACT_QUARANTINE_METADATA_BYTES",
    "ArtifactQuarantineIO",
]
