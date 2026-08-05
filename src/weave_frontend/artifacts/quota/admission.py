"""Owner-attached quota admission context managers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .service import ArtifactQuotaService


@contextmanager
def artifact_quota_admission(
    owner: Any,
    *,
    family: str,
    temporary: Path,
    final: Path,
) -> Iterator[dict[str, Any] | None]:
    """Admit an exact staged directory for a service with an attached quota guard."""

    quota = _attached_quota(owner)
    if quota is None:
        yield None
        return
    with quota.admit(
        family=family,
        temporary=temporary,
        final=final,
    ) as evidence:
        yield evidence


@contextmanager
def artifact_quota_publication_lock(
    owner: Any,
    *,
    family: str,
    final: Path,
) -> Iterator[dict[str, Any] | None]:
    """Admit an existing temporary-prefix stage and hold the global lock."""

    quota = _attached_quota(owner)
    if quota is None:
        yield None
        return
    with quota.admit_staged_prefix(family=family, final=final) as evidence:
        yield evidence


def _attached_quota(owner: Any) -> ArtifactQuotaService | None:
    quota = getattr(owner, "artifact_quota", None)
    if quota is None:
        return None
    if not isinstance(quota, ArtifactQuotaService):
        raise RuntimeError("attached artifact_quota has an unsupported type")
    return quota


__all__ = [
    "artifact_quota_admission",
    "artifact_quota_publication_lock",
]
