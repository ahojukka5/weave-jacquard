"""Stable no-follow logical accounting for selected retention entries."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Any

from ...errors import ValidationError
from .policy import hash_json, validate_nonnegative, validate_positive

ARTIFACT_RETENTION_ENTRY_SNAPSHOT_FORMAT = "weave-artifact-retention-entry-snapshot-v1"
ARTIFACT_RETENTION_RELOCATION_SNAPSHOT_FORMAT = "weave-artifact-retention-relocation-snapshot-v1"
MAX_RETENTION_SCAN_ENTRIES = 1_000_000
MAX_RETENTION_SCAN_DEPTH = 64
MAX_RETENTION_FILE_BYTES = 1024**4
_HASH_CHUNK_BYTES = 1024 * 1024


class ArtifactRetentionAccountant:
    """Measure selected entries twice without following links."""

    def __init__(
        self,
        inventory: Any,
        *,
        max_scan_entries: int = MAX_RETENTION_SCAN_ENTRIES,
        max_scan_depth: int = MAX_RETENTION_SCAN_DEPTH,
        max_file_bytes: int = MAX_RETENTION_FILE_BYTES,
    ) -> None:
        validate_positive("max_scan_entries", max_scan_entries)
        validate_nonnegative("max_scan_depth", max_scan_depth)
        validate_positive("max_file_bytes", max_file_bytes)
        self.inventory = inventory
        self.max_scan_entries = max_scan_entries
        self.max_scan_depth = max_scan_depth
        self.max_file_bytes = max_file_bytes

    def measure(
        self,
        path: Path,
        entries_remaining: int,
    ) -> tuple[dict[str, Any], int]:
        """Return stable projected logical recovery and remaining scan budget."""

        captured, entries_remaining = self.capture(path, entries_remaining)
        captured.pop("relocation_snapshot_id")
        return captured, entries_remaining

    def capture(
        self,
        path: Path,
        entries_remaining: int,
    ) -> tuple[dict[str, Any], int]:
        """Return stable accounting plus a rename-invariant snapshot identity."""

        first, entries_remaining = self._scan(path, entries_remaining)
        second, entries_remaining = self._scan(path, entries_remaining)
        if first != second:
            raise ValidationError(
                "ARTIFACT_RETENTION_ENTRY_CHANGED",
                "selected entry changed during projected-recovery accounting",
            )
        root_id = self._relative_id(".")
        relocation = [
            (
                {key: value for key, value in item.items() if key != "ctime_ns"}
                if item["relative_path_id"] == root_id
                else item
            )
            for item in first
        ]
        return (
            {
                "logical_bytes": sum(
                    item["size"] for item in first if item["entry_type"] == "regular_file"
                ),
                "regular_files": sum(item["entry_type"] == "regular_file" for item in first),
                "directories": sum(item["entry_type"] == "directory" for item in first),
                "symlinks": sum(item["entry_type"] == "symlink" for item in first),
                "special_entries": sum(item["entry_type"] == "special" for item in first),
                "entries_scanned": len(first),
                "entry_snapshot_id": hash_json(
                    {
                        "format": ARTIFACT_RETENTION_ENTRY_SNAPSHOT_FORMAT,
                        "entries": first,
                    }
                ),
                "relocation_snapshot_id": hash_json(
                    {
                        "format": ARTIFACT_RETENTION_RELOCATION_SNAPSHOT_FORMAT,
                        "entries": relocation,
                    }
                ),
            },
            entries_remaining,
        )

    def _scan(
        self,
        root: Path,
        entries_remaining: int,
    ) -> tuple[list[dict[str, Any]], int]:
        stack = [(root, ".", 0)]
        records = []
        while stack:
            path, relative, depth = stack.pop()
            if entries_remaining <= 0:
                raise ValidationError(
                    "ARTIFACT_RETENTION_SCAN_LIMIT_EXCEEDED",
                    "planning exceeds its bounded filesystem scan limit",
                )
            entries_remaining -= 1
            try:
                value = path.lstat()
            except OSError as exc:
                raise ValidationError(
                    "ARTIFACT_RETENTION_SCAN_FAILED",
                    "cannot inspect a selected retained entry",
                ) from exc
            entry_type = self.inventory._entry_type(value.st_mode)
            record = {
                "relative_path_id": self._relative_id(relative),
                "entry_type": entry_type,
                "mode": stat.S_IFMT(value.st_mode),
                "size": value.st_size,
                "mtime_ns": value.st_mtime_ns,
                "ctime_ns": value.st_ctime_ns,
                "device": value.st_dev,
                "inode": value.st_ino,
            }
            if entry_type == "regular_file":
                record["content_sha256"] = self._hash_regular_file(path, value)
            records.append(record)
            if entry_type != "directory":
                continue
            try:
                with os.scandir(path) as iterator:
                    children = sorted(
                        ((Path(item.path), item.name) for item in iterator),
                        key=lambda item: item[1],
                        reverse=True,
                    )
            except OSError as exc:
                raise ValidationError(
                    "ARTIFACT_RETENTION_SCAN_FAILED",
                    "cannot enumerate a selected retained directory",
                ) from exc
            if children and depth >= self.max_scan_depth:
                raise ValidationError(
                    "ARTIFACT_RETENTION_DEPTH_EXCEEDED",
                    "planning exceeds its bounded directory depth",
                )
            for child, name in children:
                relative_child = name if relative == "." else f"{relative}/{name}"
                stack.append((child, relative_child, depth + 1))
        records.sort(key=lambda item: item["relative_path_id"])
        return records, entries_remaining

    def _hash_regular_file(self, path: Path, expected: os.stat_result) -> str:
        if expected.st_size > self.max_file_bytes:
            raise ValidationError(
                "ARTIFACT_RETENTION_FILE_LIMIT_EXCEEDED",
                "selected regular file exceeds the bounded hashing limit",
            )
        flags = os.O_RDONLY
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise ValidationError(
                "ARTIFACT_RETENTION_ENTRY_CHANGED",
                "selected regular file changed before content hashing",
            ) from exc
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or not self._same_entry(expected, before):
                raise ValidationError(
                    "ARTIFACT_RETENTION_ENTRY_CHANGED",
                    "selected regular file changed before content hashing",
                )
            digest = hashlib.sha256()
            bytes_read = 0
            while True:
                chunk = os.read(descriptor, _HASH_CHUNK_BYTES)
                if not chunk:
                    break
                bytes_read += len(chunk)
                if bytes_read > self.max_file_bytes:
                    raise ValidationError(
                        "ARTIFACT_RETENTION_FILE_LIMIT_EXCEEDED",
                        "selected regular file exceeds the bounded hashing limit",
                    )
                digest.update(chunk)
            after = os.fstat(descriptor)
            if not self._same_entry(before, after) or bytes_read != after.st_size:
                raise ValidationError(
                    "ARTIFACT_RETENTION_ENTRY_CHANGED",
                    "selected regular file changed during content hashing",
                )
            try:
                current = path.lstat()
            except OSError as exc:
                raise ValidationError(
                    "ARTIFACT_RETENTION_ENTRY_CHANGED",
                    "selected regular file changed after content hashing",
                ) from exc
            if not self._same_entry(after, current):
                raise ValidationError(
                    "ARTIFACT_RETENTION_ENTRY_CHANGED",
                    "selected regular file changed after content hashing",
                )
            return digest.hexdigest()
        finally:
            os.close(descriptor)

    @staticmethod
    def _same_entry(left: os.stat_result, right: os.stat_result) -> bool:
        return (
            stat.S_IFMT(left.st_mode),
            left.st_dev,
            left.st_ino,
            left.st_size,
            left.st_mtime_ns,
            left.st_ctime_ns,
        ) == (
            stat.S_IFMT(right.st_mode),
            right.st_dev,
            right.st_ino,
            right.st_size,
            right.st_mtime_ns,
            right.st_ctime_ns,
        )

    @staticmethod
    def _relative_id(value: str) -> str:
        return hashlib.sha256(
            ARTIFACT_RETENTION_ENTRY_SNAPSHOT_FORMAT.encode("utf-8") + b"\0" + value.encode("utf-8")
        ).hexdigest()


__all__ = [
    "ARTIFACT_RETENTION_ENTRY_SNAPSHOT_FORMAT",
    "ARTIFACT_RETENTION_RELOCATION_SNAPSHOT_FORMAT",
    "MAX_RETENTION_FILE_BYTES",
    "MAX_RETENTION_SCAN_DEPTH",
    "MAX_RETENTION_SCAN_ENTRIES",
    "ArtifactRetentionAccountant",
]
