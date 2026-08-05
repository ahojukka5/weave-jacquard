"""Production workspace with bounded semantic revision-state admission."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .compiler import (
    CapabilityAwareWeavecValidator,
    CapabilityGrammarIndex,
    WeavecCapabilities,
    WeavecValidator,
)
from .concurrent_workspace import SExpressionWorkspace as _ConcurrentWorkspace
from .errors import NotFoundError, ValidationError
from .snapshot_codec import SnapshotIntegrityError, load_revision_state


class SExpressionWorkspace(_ConcurrentWorkspace):
    """Race-safe workspace that verifies every loaded immutable revision state."""

    def __init__(
        self,
        path: str | Path,
        *,
        weavec_source_root: str | Path | None = None,
        weavec_binary: str | Path | None = None,
    ) -> None:
        self._validator: Any
        super().__init__(
            path,
            weavec_source_root=weavec_source_root,
            weavec_binary=weavec_binary,
        )
        self.capabilities = WeavecCapabilities(
            weavec_binary,
            source_root=weavec_source_root,
        )
        self.grammar = CapabilityGrammarIndex(
            weavec_source_root,
            capabilities=self.capabilities,
        )
        self.validator = self._validator

    @property
    def validator(self) -> Any:
        return self._validator

    @validator.setter
    def validator(self, value: Any) -> None:
        """Keep production compiler validators behind the capability handshake."""

        capabilities = getattr(self, "capabilities", None)
        if (
            capabilities is None
            or isinstance(value, CapabilityAwareWeavecValidator)
            or not isinstance(value, WeavecValidator)
        ):
            self._validator = value
            return
        self._validator = CapabilityAwareWeavecValidator(
            value._configured_binary,
            value.source_root,
            capabilities=capabilities,
            timeout_seconds=value.timeout_seconds,
            max_output_bytes=value.max_output_bytes,
            max_wir_bytes=value.max_wir_bytes,
            environment_fallback=value.environment_fallback,
        )

    def _state_at_revision(self, revision_id: str) -> dict[str, dict[str, Any]]:
        row = self.db.connection.execute(
            "SELECT root_hash FROM revisions WHERE id = ?",
            (revision_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"revision {revision_id!r} not found")
        try:
            state = load_revision_state(
                self.db.connection,
                revision_id,
                expected_root_hash=str(row["root_hash"]),
            )
        except SnapshotIntegrityError as exc:
            raise ValidationError(
                "CORRUPT_REVISION_STATE",
                f"stored revision state failed semantic integrity verification: {exc.code}",
            ) from exc
        return state.modules


__all__ = ["SExpressionWorkspace"]
