"""Final manifest and aggregate-quota admission for immutable database backups."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .artifact_quota import ArtifactQuotaService, artifact_quota_admission
from .database_backup import DatabaseBackupService as _DatabaseBackupService
from .errors import ArtifactIntegrityError, ValidationError

MAX_DATABASE_BACKUP_STAGE_ROOT_ENTRIES = 65_536
MAX_DATABASE_BACKUP_STAGES = 16
_DATABASE_BACKUP_STAGE_PREFIX = ".database-backup-"
_DATABASE_BACKUP_FILES = frozenset({"backup-manifest.json", "database.sqlite3"})


class DatabaseBackupService(_DatabaseBackupService):
    """Reject mutable evidence and quota-admit verified backup publication."""

    artifact_quota_family = "database_backups"

    def _verify_manifest(
        self,
        manifest: dict[str, Any],
        directory: Path,
        *,
        expected_id: str,
    ) -> None:
        super()._verify_manifest(manifest, directory, expected_id=expected_id)
        if manifest.get("cached") is not False:
            raise ArtifactIntegrityError(
                "database backup stored cache state is invalid"
            )
        self._verify_directory_layout(directory)

    @contextmanager
    def _publication_lock(self, final: Path) -> Iterator[None]:
        """Acquire aggregate quota admission before the per-backup publication lock."""

        quota = getattr(self, "artifact_quota", None)
        if quota is not None and not isinstance(quota, ArtifactQuotaService):
            raise RuntimeError("attached artifact_quota has an unsupported type")
        if quota is None or quota.max_bytes is None:
            with super()._publication_lock(final):
                yield
            return

        missing_stage: ValidationError | None = None
        for temporary in self._quota_stages(final):
            try:
                with artifact_quota_admission(
                    self,
                    family=self.artifact_quota_family,
                    temporary=temporary,
                    final=final,
                ):
                    with super()._publication_lock(final):
                        yield
                    return
            except ValidationError as exc:
                if exc.code != "INVALID_ARTIFACT_QUOTA_PATH":
                    raise
                missing_stage = exc

        raise ValidationError(
            "ARTIFACT_STORAGE_STAGE_NOT_FOUND",
            "database backup publication has no available verified matching stage",
        ) from missing_stage

    def _quota_stages(self, final: Path) -> tuple[Path, ...]:
        """Locate bounded verified stages whose manifests bind the final backup ID."""

        matches: list[Path] = []
        try:
            with os.scandir(self.backup_root) as iterator:
                for index, entry in enumerate(iterator):
                    if index >= MAX_DATABASE_BACKUP_STAGE_ROOT_ENTRIES:
                        raise ValidationError(
                            "ARTIFACT_STORAGE_QUOTA_ROOT_LIMIT_EXCEEDED",
                            "database backup root exceeds the bounded quota entry limit "
                            f"{MAX_DATABASE_BACKUP_STAGE_ROOT_ENTRIES}",
                        )
                    if not entry.name.startswith(_DATABASE_BACKUP_STAGE_PREFIX):
                        continue
                    try:
                        metadata = entry.stat(follow_symlinks=False)
                    except OSError as exc:
                        raise ValidationError(
                            "ARTIFACT_STORAGE_SCAN_FAILED",
                            "database backup staging changed during quota admission",
                        ) from exc
                    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(
                        metadata.st_mode
                    ):
                        continue
                    directory = Path(entry.path)
                    try:
                        manifest = self._read_manifest(
                            directory / "backup-manifest.json"
                        )
                        if manifest.get("backup_id") != final.name:
                            continue
                        self._verify_manifest(
                            manifest,
                            directory,
                            expected_id=final.name,
                        )
                    except (ArtifactIntegrityError, ValidationError):
                        continue
                    matches.append(directory)
                    if len(matches) > MAX_DATABASE_BACKUP_STAGES:
                        raise ValidationError(
                            "ARTIFACT_STORAGE_STAGE_LIMIT_EXCEEDED",
                            "database backup publication has too many matching stages",
                        )
        except ValidationError:
            raise
        except OSError as exc:
            raise ValidationError(
                "ARTIFACT_STORAGE_SCAN_FAILED",
                "cannot enumerate database backup staging",
            ) from exc

        if not matches:
            raise ValidationError(
                "ARTIFACT_STORAGE_STAGE_NOT_FOUND",
                "database backup publication has no verified matching stage",
            )
        return tuple(sorted(matches, key=lambda path: path.name))

    @staticmethod
    def _verify_directory_layout(directory: Path) -> None:
        """Require the immutable backup directory to contain exactly two regular files."""

        try:
            with os.scandir(directory) as iterator:
                entries = list(iterator)
        except OSError as exc:
            raise ArtifactIntegrityError(
                "cannot enumerate database backup directory"
            ) from exc

        if {entry.name for entry in entries} != _DATABASE_BACKUP_FILES:
            raise ArtifactIntegrityError(
                "database backup directory layout is invalid"
            )
        for entry in entries:
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise ArtifactIntegrityError(
                    "cannot inspect database backup directory entry"
                ) from exc
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise ArtifactIntegrityError(
                    "database backup directory entries must be regular files"
                )


__all__ = [
    "MAX_DATABASE_BACKUP_STAGE_ROOT_ENTRIES",
    "MAX_DATABASE_BACKUP_STAGES",
    "DatabaseBackupService",
]
