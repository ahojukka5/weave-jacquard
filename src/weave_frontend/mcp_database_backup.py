"""Production MCP registration for verified online database backups."""

from __future__ import annotations

from typing import Any

from .database_backup import DEFAULT_DATABASE_BACKUP_TIMEOUT_SECONDS
from .mcp_server import _result, mcp, workspace
from .runtime_container import runtime_config, runtime_service
from .verified_database_backup import DatabaseBackupService

DATABASE_BACKUP_ROOT_ENV = "WEAVE_DATABASE_BACKUP_ROOT"


@runtime_service("database_backups", depends_on=("workspace",))
def database_backups() -> DatabaseBackupService:
    """Return the shared immutable database-backup service."""

    return DatabaseBackupService(
        workspace().db,
        backup_root=runtime_config().database_backup_root,
    )


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
