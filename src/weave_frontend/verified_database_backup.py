"""Final manifest admission rules for immutable database backups."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .database_backup import DatabaseBackupService as _DatabaseBackupService
from .errors import ArtifactIntegrityError


class DatabaseBackupService(_DatabaseBackupService):
    """Reject mutable cache-state tampering before accepting backup evidence."""

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


__all__ = ["DatabaseBackupService"]
