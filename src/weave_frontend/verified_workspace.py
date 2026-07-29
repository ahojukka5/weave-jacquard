"""Production workspace with bounded semantic revision-state admission."""

from __future__ import annotations

from typing import Any

from .concurrent_workspace import SExpressionWorkspace as _ConcurrentWorkspace
from .errors import NotFoundError, ValidationError
from .snapshot_codec import SnapshotIntegrityError, load_revision_state


class SExpressionWorkspace(_ConcurrentWorkspace):
    """Race-safe workspace that verifies every loaded immutable revision state."""

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
