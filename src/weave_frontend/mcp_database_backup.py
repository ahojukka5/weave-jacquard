"""Production MCP registration for verified online database backups."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from .database_backup import DEFAULT_DATABASE_BACKUP_TIMEOUT_SECONDS
from .mcp_server import _result, mcp, workspace
from .verified_database_backup import DatabaseBackupService

DATABASE_BACKUP_ROOT_ENV = "WEAVE_DATABASE_BACKUP_ROOT"


def _install_configuration_contract() -> None:
    """Bind backup-root configuration before application manifest finalization."""

    from . import application

    names = set(application.PUBLIC_CONFIGURATION_VARIABLES)
    names.add(DATABASE_BACKUP_ROOT_ENV)
    application.PUBLIC_CONFIGURATION_VARIABLES = tuple(sorted(names))


@lru_cache(maxsize=1)
def database_backups() -> DatabaseBackupService:
    """Return the shared immutable database-backup service."""

    return DatabaseBackupService(workspace().db)


def install_capability() -> None:
    """Install configuration identity and discard stale backup-root composition."""

    _install_configuration_contract()
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
