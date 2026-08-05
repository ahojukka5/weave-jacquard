"""Aggregate artifact quota policy, reporting, locking, and admission."""

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

from ...errors import ArtifactQuotaExceededError, ValidationError
from ..storage import ArtifactStorageService

ARTIFACT_QUOTA_REPORT_FORMAT = "weave-artifact-quota-report-v1"
ARTIFACT_QUOTA_POLICY_FORMAT = "weave-artifact-quota-policy-v1"
ARTIFACT_QUOTA_LOCK_ID_FORMAT = "weave-artifact-quota-lock-v1"
ARTIFACT_QUOTA_ENV = "WEAVE_ARTIFACT_MAX_BYTES"
MAX_ARTIFACT_QUOTA_BYTES = 9_223_372_036_854_775_807
MAX_ARTIFACT_QUOTA_ROOT_ENTRIES = 65_536
MAX_ARTIFACT_STAGED_CANDIDATES = 16


def parse_artifact_quota(value: str | None) -> int | None:
    """Parse an optional non-negative decimal logical-byte ceiling."""

    if value is None or value == "":
        return None
    if value != value.strip() or not value.isascii() or not value.isdecimal():
        raise ValueError(f"{ARTIFACT_QUOTA_ENV} must be an unsigned decimal byte count")
    parsed = int(value)
    if parsed > MAX_ARTIFACT_QUOTA_BYTES:
        raise ValueError(f"{ARTIFACT_QUOTA_ENV} must not exceed {MAX_ARTIFACT_QUOTA_BYTES}")
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
                f"max_bytes must be null or an integer between 0 and {MAX_ARTIFACT_QUOTA_BYTES}"
            )
        raw_lock_path = Path(lock_path)
        if raw_lock_path.name in {"", ".", ".."}:
            raise ValueError("lock_path must identify a file")
        self.accounting = accounting
        self.lock_path = raw_lock_path.parent.resolve() / raw_lock_path.name
        self.max_bytes = max_bytes
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

    def report(self) -> dict[str, Any]:
        """Return observed storage plus the retained-byte admission policy state."""

        with self._lock():
            storage = self.accounting.report()
            retained = self.accounting._report(
                excluded_paths=(),
                exclude_internal_entries=True,
            )
        observed_bytes = int(storage["aggregate"]["logical_bytes"])
        current_bytes = int(retained["aggregate"]["logical_bytes"])
        internal_bytes = max(0, observed_bytes - current_bytes)
        available = None if self.max_bytes is None else max(0, self.max_bytes - current_bytes)
        policy_payload = {
            "format": ARTIFACT_QUOTA_POLICY_FORMAT,
            "enabled": self.max_bytes is not None,
            "max_logical_bytes": self.max_bytes,
            "current_logical_bytes": current_bytes,
            "observed_logical_bytes": observed_bytes,
            "internal_logical_bytes": internal_bytes,
            "available_logical_bytes": available,
            "exceeded": (self.max_bytes is not None and current_bytes > self.max_bytes),
            "enforcement": (
                "interprocess-publication-admission" if self.max_bytes is not None else "disabled"
            ),
            "lock_id": self._lock_id(),
            "retained_storage_snapshot_id": retained["storage_snapshot_id"],
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
                    "retained_storage_snapshot_id": retained["storage_snapshot_id"],
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

        root = self._family_root(family)
        temporary_path = self._contained_path(
            temporary,
            root,
            subject="temporary",
            require_directory=True,
        )
        final_path = self._contained_path(
            final,
            root,
            subject="final",
            require_directory=False,
        )
        if temporary_path == final_path:
            raise RuntimeError("temporary and final artifact directories must differ")

        with self._lock():
            current_report = self.accounting._report(
                excluded_paths=(temporary_path, final_path),
                exclude_internal_entries=True,
            )
            staged_bytes = self._logical_bytes(temporary_path)
            current_bytes = int(current_report["aggregate"]["logical_bytes"])
            projected_bytes = current_bytes + staged_bytes
            self._require_within_quota(
                family=family,
                current_bytes=current_bytes,
                staged_bytes=staged_bytes,
                projected_bytes=projected_bytes,
            )
            yield self._admission_evidence(
                family=family,
                current_bytes=current_bytes,
                staged_bytes=staged_bytes,
                projected_bytes=projected_bytes,
                storage_snapshot_id=current_report["storage_snapshot_id"],
            )

    @contextmanager
    def admit_staged_prefix(
        self,
        *,
        family: str,
        final: Path,
    ) -> Iterator[dict[str, Any] | None]:
        """Admit a service whose temporary directory is named from its final ID."""

        if self.max_bytes is None:
            yield None
            return

        root = self._family_root(family)
        final_path = self._contained_path(
            final,
            root,
            subject="final",
            require_directory=False,
        )
        prefix = f".{final_path.name}-"
        with self._lock():
            staged = self._staged_directories(root, prefix=prefix)
            if not staged:
                raise ValidationError(
                    "ARTIFACT_STORAGE_STAGE_NOT_FOUND",
                    "artifact publication has no matching staged directory",
                )
            current_report = self.accounting._report(
                excluded_paths=(final_path,),
                exclude_internal_entries=True,
            )
            current_bytes = int(current_report["aggregate"]["logical_bytes"])
            staged_bytes = max(self._logical_bytes(path) for path in staged)
            projected_bytes = current_bytes + staged_bytes
            self._require_within_quota(
                family=family,
                current_bytes=current_bytes,
                staged_bytes=staged_bytes,
                projected_bytes=projected_bytes,
            )
            yield self._admission_evidence(
                family=family,
                current_bytes=current_bytes,
                staged_bytes=staged_bytes,
                projected_bytes=projected_bytes,
                storage_snapshot_id=current_report["storage_snapshot_id"],
            )

    def _staged_directories(self, root: Path, *, prefix: str) -> list[Path]:
        result: list[Path] = []
        try:
            with os.scandir(root) as iterator:
                for index, entry in enumerate(iterator):
                    if index >= MAX_ARTIFACT_QUOTA_ROOT_ENTRIES:
                        raise ValidationError(
                            "ARTIFACT_STORAGE_QUOTA_ROOT_LIMIT_EXCEEDED",
                            "artifact family root exceeds the bounded quota entry limit "
                            f"{MAX_ARTIFACT_QUOTA_ROOT_ENTRIES}",
                        )
                    if not entry.name.startswith(prefix):
                        continue
                    try:
                        metadata = entry.stat(follow_symlinks=False)
                    except OSError as exc:
                        raise ValidationError(
                            "ARTIFACT_STORAGE_SCAN_FAILED",
                            "artifact staging changed during quota admission",
                        ) from exc
                    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                        continue
                    result.append(Path(entry.path))
                    if len(result) > MAX_ARTIFACT_STAGED_CANDIDATES:
                        raise ValidationError(
                            "ARTIFACT_STORAGE_STAGE_LIMIT_EXCEEDED",
                            "artifact publication has too many matching staged directories",
                        )
        except ValidationError:
            raise
        except OSError as exc:
            raise ValidationError(
                "ARTIFACT_STORAGE_SCAN_FAILED",
                "cannot enumerate artifact family staging",
            ) from exc
        return result

    @staticmethod
    def _logical_bytes(path: Path) -> int:
        report = ArtifactStorageService({"staged_publication": path}).report()
        return int(report["aggregate"]["logical_bytes"])

    def _family_root(self, family: str) -> Path:
        root = self.accounting.roots.get(family)
        if root is None:
            raise RuntimeError(f"unknown artifact quota family {family!r}")
        return root

    def _require_within_quota(
        self,
        *,
        family: str,
        current_bytes: int,
        staged_bytes: int,
        projected_bytes: int,
    ) -> None:
        assert self.max_bytes is not None
        if projected_bytes > self.max_bytes:
            raise ArtifactQuotaExceededError(
                family=family,
                quota_bytes=self.max_bytes,
                current_bytes=current_bytes,
                staged_bytes=staged_bytes,
                projected_bytes=projected_bytes,
            )

    def _admission_evidence(
        self,
        *,
        family: str,
        current_bytes: int,
        staged_bytes: int,
        projected_bytes: int,
        storage_snapshot_id: str,
    ) -> dict[str, Any]:
        assert self.max_bytes is not None
        return {
            "family": family,
            "quota_bytes": self.max_bytes,
            "current_bytes": current_bytes,
            "staged_bytes": staged_bytes,
            "projected_bytes": projected_bytes,
            "storage_snapshot_id": storage_snapshot_id,
        }

    @staticmethod
    def _contained_path(
        path: Path,
        root: Path,
        *,
        subject: str,
        require_directory: bool,
    ) -> Path:
        try:
            parent = path.parent.resolve()
        except OSError as exc:
            raise ValidationError(
                "INVALID_ARTIFACT_QUOTA_PATH",
                f"cannot resolve the {subject} artifact directory parent",
            ) from exc
        if parent != root or path.name in {"", ".", ".."}:
            raise ValidationError(
                "INVALID_ARTIFACT_QUOTA_PATH",
                f"{subject} artifact directory must be a direct child of its family root",
            )
        candidate = root / path.name
        if require_directory:
            try:
                metadata = candidate.lstat()
            except OSError as exc:
                raise ValidationError(
                    "INVALID_ARTIFACT_QUOTA_PATH",
                    f"{subject} artifact directory is unavailable",
                ) from exc
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise ValidationError(
                    "INVALID_ARTIFACT_QUOTA_PATH",
                    f"{subject} artifact path must be a non-symlink directory",
                )
        return candidate

    @contextmanager
    def _lock(self) -> Iterator[None]:
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self.lock_path, flags, 0o600)
        except OSError as exc:
            raise ValidationError(
                "ARTIFACT_STORAGE_QUOTA_LOCK_UNAVAILABLE",
                "cannot open the artifact quota lock",
            ) from exc
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise ValidationError(
                    "ARTIFACT_STORAGE_QUOTA_LOCK_UNAVAILABLE",
                    "artifact quota lock must be a regular file",
                )
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
            except OSError as exc:
                raise ValidationError(
                    "ARTIFACT_STORAGE_QUOTA_LOCK_UNAVAILABLE",
                    "cannot acquire the artifact quota lock",
                ) from exc
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
    "MAX_ARTIFACT_QUOTA_ROOT_ENTRIES",
    "MAX_ARTIFACT_STAGED_CANDIDATES",
    "ArtifactQuotaService",
    "parse_artifact_quota",
]
