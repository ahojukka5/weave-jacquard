"""Lifecycle-aware retained versus quarantine logical-byte accounting."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Any

from .artifact_storage import (
    MAX_ARTIFACT_SCAN_DEPTH,
    MAX_ARTIFACT_SCAN_ENTRIES,
    ArtifactStorageService,
)
from .errors import ValidationError

ARTIFACT_STORAGE_LIFECYCLE_FORMAT = "weave-artifact-storage-lifecycle-v1"
_QUARANTINE_CAPSULE_NAME = re.compile(r"^\.quarantine-[0-9a-f]{64}$")


class ArtifactLifecycleStorageService(ArtifactStorageService):
    """Extend aggregate storage evidence with quarantine namespace usage."""

    def report(self) -> dict[str, Any]:
        """Return normal accounting plus retained and quarantined byte totals."""

        base = super().report()
        remaining = MAX_ARTIFACT_SCAN_ENTRIES
        by_family: dict[str, int] = {}
        for name in sorted(self.roots):
            value, remaining = self._quarantined_bytes(
                self.roots[name],
                remaining,
            )
            by_family[name] = value

        families = []
        for family in base["families"]:
            quarantined = by_family[family["family"]]
            if quarantined > family["logical_bytes"]:
                raise ValidationError(
                    "ARTIFACT_STORAGE_QUARANTINE_ACCOUNTING_INVALID",
                    "quarantine usage exceeds complete family usage",
                )
            families.append(
                {
                    **family,
                    "usage": {
                        "retained_logical_bytes": (family["logical_bytes"] - quarantined),
                        "quarantined_logical_bytes": quarantined,
                    },
                }
            )

        usage = {
            "retained_logical_bytes": sum(
                item["usage"]["retained_logical_bytes"] for item in families
            ),
            "quarantined_logical_bytes": sum(
                item["usage"]["quarantined_logical_bytes"] for item in families
            ),
        }
        payload = {key: value for key, value in base.items() if key != "storage_snapshot_id"}
        payload.update(
            {
                "lifecycle_format": ARTIFACT_STORAGE_LIFECYCLE_FORMAT,
                "quarantine_accounting": ("reserved-top-level-capsule-namespace"),
                "usage": usage,
                "families": families,
            }
        )
        return {
            **payload,
            "storage_snapshot_id": self._hash_json(payload),
        }

    def _quarantined_bytes(
        self,
        root: Path,
        entries_remaining: int,
    ) -> tuple[int, int]:
        try:
            metadata = root.lstat()
        except OSError as exc:
            raise ValidationError(
                "ARTIFACT_STORAGE_ROOT_UNAVAILABLE",
                "artifact storage root is unavailable during lifecycle accounting",
            ) from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ValidationError(
                "ARTIFACT_STORAGE_ROOT_INVALID",
                "artifact storage root must be a non-symlink directory",
            )
        total = 0
        try:
            with os.scandir(root) as iterator:
                capsules = sorted(
                    Path(item.path)
                    for item in iterator
                    if _QUARANTINE_CAPSULE_NAME.fullmatch(item.name)
                )
        except OSError as exc:
            raise ValidationError(
                "ARTIFACT_STORAGE_SCAN_FAILED",
                "cannot enumerate quarantine capsule namespace",
            ) from exc
        for capsule in capsules:
            value, entries_remaining = self._scan_capsule(
                capsule,
                entries_remaining,
            )
            total += value
        return total, entries_remaining

    def _scan_capsule(
        self,
        capsule: Path,
        entries_remaining: int,
    ) -> tuple[int, int]:
        logical_bytes = 0
        stack = [(capsule, 0)]
        while stack:
            path, depth = stack.pop()
            if entries_remaining <= 0:
                raise ValidationError(
                    "ARTIFACT_STORAGE_SCAN_LIMIT_EXCEEDED",
                    "quarantine accounting exceeds the bounded scan entry limit",
                )
            entries_remaining -= 1
            try:
                metadata = path.lstat()
            except OSError as exc:
                raise ValidationError(
                    "ARTIFACT_STORAGE_SCAN_FAILED",
                    "quarantine capsule changed during accounting",
                ) from exc
            mode = metadata.st_mode
            if stat.S_ISREG(mode):
                logical_bytes += metadata.st_size
                continue
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                continue
            try:
                with os.scandir(path) as iterator:
                    children = sorted(
                        (Path(item.path) for item in iterator),
                        key=lambda item: item.name,
                        reverse=True,
                    )
            except OSError as exc:
                raise ValidationError(
                    "ARTIFACT_STORAGE_SCAN_FAILED",
                    "cannot enumerate quarantine capsule during accounting",
                ) from exc
            if children and depth >= MAX_ARTIFACT_SCAN_DEPTH:
                raise ValidationError(
                    "ARTIFACT_STORAGE_DEPTH_EXCEEDED",
                    "quarantine accounting exceeds the bounded directory depth",
                )
            for child in children:
                stack.append((child, depth + 1))
        return logical_bytes, entries_remaining


__all__ = [
    "ARTIFACT_STORAGE_LIFECYCLE_FORMAT",
    "ArtifactLifecycleStorageService",
]
