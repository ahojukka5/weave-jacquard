"""Production MCP registration for verified online database backups."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from .database_backup import (
    DEFAULT_DATABASE_BACKUP_TIMEOUT_SECONDS,
    DatabaseBackupService,
)
from .mcp_server import _result, mcp, workspace


@lru_cache(maxsize=1)
def database_backups() -> DatabaseBackupService:
    """Return the shared immutable database-backup service."""

    return DatabaseBackupService(workspace().db)


def install_capability() -> None:
    """Discard stale backup-root composition during application reinstallation."""

    database_backups.cache_clear()


@mcp.tool()
def database_backup_create(
    timeout_seconds: int = DEFAULT_DATABASE_BACKUP_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Create and verify one immutable online SQLite backup."""

    return _result(
        lambda: database_backups().create(timeout_seconds=timeout_seconds)
    )


@mcp.tool()
def database_backup_get(backup_id: str) -> dict[str, Any]:
    """Read and reverify one immutable database backup manifest."""

    return _result(lambda: database_backups().get(backup_id))
