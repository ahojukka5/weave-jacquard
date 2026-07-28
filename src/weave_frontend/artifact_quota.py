"""Interprocess logical-byte quota admission for retained artifact publication."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .artifact_storage import ArtifactStorageService
from .errors import ArtifactQuotaExceededError, ValidationError

ARTIFACT_QUOTA_REPORT_FORMAT = "weave-artifact-quota-report-v1"
ARTIFACT_QUOTA_POLICY_FORMAT = "weave-artifact-quota-policy-v1"
ARTIFACT_QUOTA_LOCK_ID_FORMAT = "weave-artifact-quota-lock-v1"
ARTIFACT_QUOTA_ENV = "WEAVE_ARTIFACT_MAX_BYTES"
MAX_ARTIFACT_QUOTA_BYTES = 9_223_372_036_854_775_807


def parse_artifact_quota(value: str | None) -> int | None:
    """Parse an optional non-negative decimal logical-byte ceiling."""

    if value is None or value == "":
        return None
    if value != value.strip() or not value.isascii() or not value.isdecimal():
        raise ValueError(
            f"{ARTIFACT_QUOTA_ENV} must be an unsigned decimal byte count"
        )
    parsed = int(value)
    if parsed > MAX_ARTIFACT_QUOTA_BYTES:
        raise ValueError(
            f"{ARTIFACT_QUOTA_ENV} must not exceed {MAX_ARTIFACT_QUOTA_BYTES}"
        )
    return parsed


class ArtifactQuotaService:
    """Serialize publication admission against one complete configured root graph."""

    def __init__(
        self,
        accounting: ArtifactStorageService,
        *,
        lock_path: str | Path,
        max_bytes: int | None,
    ) -> None:
        if max_bytes is not None and (
            isinstance(max_bytes, bool)
            or not isinstance(max_bytes, int)
            or not 0 <= max_bytes <= MAX_ARTIFACT_QUOTA_BYTES
        ):
            raise ValueError(
                "max_bytes must be null or an integer between 0 and "
                f"{MAX_ARTIFACT_QUOTA_BYTES}"
            )
        self.accounting = accounting
        self.lock_path = Path(lock_path).resolve()
        self.max_bytes = max_bytes
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

    def report(self) -> dict[str, Any]:
        """Return storage accounting plus the active aggregate quota policy."""

        with self._lock():
            storage = self.accounting.report()
        current = int(storage["aggregate"]["logical_bytes"])
        available = (
            None if self.max_bytes is None else max(0, self.max_bytes - current)
        )
        policy_payload = {
            "format": ARTIFACT_QUOTA_POLICY_FORMAT,
            "enabled": self.max_bytes is not None,
            "max_logical_bytes": self.max_bytes,
            "current_logical_bytes": current,
            "available_logical_bytes": available,
            "exceeded": self.max_bytes is not None and current > self.max_bytes,
            "enforcement": (
                "interprocess-publication-admission"
                if self.max_bytes is not None
                else "disabled"
            ),
            "lock_id": self._lock_id(),
            "requires_shared_database_directory": True,
        }
        return {
            **storage,
            "quota": {
                **policy_payload,
                "quota_policy_id": self._hash_json(policy_payload),
            },
            "quota_snapshot_id": self._hash_json(
                {
                    "format": ARTIFACT_QUOTA_REPORT_FORMAT,
                    "storage_snapshot_id": storage["storage_snapshot_id"],
                    "policy": policy_payload,
                }
            ),
        }

    @contextmanager
    def admit(
        self,
        *,
        family: str,
        temporary: Path,
        final: Path,
    ) -> Iterator[dict[str, Any] | None]:
        """Hold the global quota lock while one exact staged directory is published."""

        if self.max_bytes is None:
            yield None
            return

        root = self.accounting.roots.get(family)
        if root is None:
            raise RuntimeError(f"unknown artifact quota family {family!r}")
        temporary_path = self._contained_path(temporary, root, subject="temporary")
        final_path = self._contained_path(final, root, subject="final")
        if temporary_path == final_path:
            raise RuntimeError("temporary and final artifact directories must differ")

        with self._lock():
            current_report = self.accounting._report(
                excluded_paths=(temporary_path, final_path),
            )
            staged_report = ArtifactStorageService(
                {"staged_publication": temporary_path}
            ).report()
            current_bytes = int(current_report["aggregate"]["logical_bytes"])
            staged_bytes = int(staged_report["aggregate"]["logical_bytes"])
            projected_bytes = current_bytes + staged_bytes
            if projected_bytes > self.max_bytes:
                raise ArtifactQuotaExceededError(
                    family=family,
                    quota_bytes=self.max_bytes,
                    current_bytes=current_bytes,
                    staged_bytes=staged_bytes,
                    projected_bytes=projected_bytes,
                )
            yield {
                "family": family,
                "quota_bytes": self.max_bytes,
                "current_bytes": current_bytes,
                "staged_bytes": staged_bytes,
                "projected_bytes": projected_bytes,
                "storage_snapshot_id": current_report["storage_snapshot_id"],
            }

    @staticmethod
    def _contained_path(path: Path, root: Path, *, subject: str) -> Path:
        try:
            resolved = path.resolve()
            resolved.relative_to(root)
        except (OSError, ValueError) as exc:
            raise ValidationError(
                "INVALID_ARTIFACT_QUOTA_PATH",
                f"{subject} artifact directory escapes its configured family root",
            ) from exc
        if resolved == root:
            raise ValidationError(
                "INVALID_ARTIFACT_QUOTA_PATH",
                f"{subject} artifact directory cannot equal its family root",
            )
        return resolved

    @contextmanager
    def _lock(self) -> Iterator[None]:
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(self.lock_path, flags, 0o600)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise RuntimeError("artifact quota lock must be a regular file")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    def _lock_id(self) -> str:
        encoded = (
            ARTIFACT_QUOTA_LOCK_ID_FORMAT.encode("utf-8")
            + b"\0"
            + str(self.lock_path).encode("utf-8")
        )
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _hash_json(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()


__all__ = [
    "ARTIFACT_QUOTA_ENV",
    "ARTIFACT_QUOTA_POLICY_FORMAT",
    "ARTIFACT_QUOTA_REPORT_FORMAT",
    "MAX_ARTIFACT_QUOTA_BYTES",
    "ArtifactQuotaService",
    "parse_artifact_quota",
]
