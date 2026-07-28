"""Domain-specific exceptions returned by the agent-facing API."""

from __future__ import annotations

from typing import Any


class WeaveFrontendError(Exception):
    """Base class for all workspace errors."""


class ValidationError(WeaveFrontendError):
    """Raised when a proposed AST mutation is invalid."""

    def __init__(self, code: str, message: str, *, node_id: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.node_id = node_id

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "node_id": self.node_id}


class DatabaseBusyError(ValidationError):
    """Raised when SQLite cannot acquire its write lock within the busy policy."""

    def __init__(self, *, busy_timeout_ms: int) -> None:
        super().__init__(
            "DATABASE_BUSY",
            "database remained busy or locked for the configured timeout",
        )
        self.busy_timeout_ms = busy_timeout_ms

    def as_dict(self) -> dict[str, Any]:
        return {
            **super().as_dict(),
            "retryable": True,
            "busy_timeout_ms": self.busy_timeout_ms,
        }


class ArtifactIntegrityError(WeaveFrontendError):
    """Raised when immutable retained artifact evidence cannot be verified."""


class NotFoundError(WeaveFrontendError):
    """Raised when a requested project object does not exist."""


class ConflictError(WeaveFrontendError):
    """Raised when a semantic three-way merge cannot be completed safely."""

    def __init__(self, conflicts: list[str]) -> None:
        super().__init__("merge conflict: " + ", ".join(conflicts))
        self.conflicts = conflicts
