"""Reusable publication guard backed by aggregate artifact quota admission."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .admission import artifact_quota_publication_lock


class QuotaPublicationLockMixin:
    """Acquire the aggregate quota lock before the normal per-artifact lock."""

    artifact_quota_family: str

    @contextmanager
    def _publication_lock(self, final: Path) -> Iterator[None]:
        family = getattr(self, "artifact_quota_family", None)
        if not isinstance(family, str) or not family:
            raise RuntimeError("artifact_quota_family must be a non-empty string")
        with artifact_quota_publication_lock(
            self,
            family=family,
            final=final,
        ):
            parent_lock = super()._publication_lock  # type: ignore[misc]
            with parent_lock(final):
                yield


__all__ = ["QuotaPublicationLockMixin"]
