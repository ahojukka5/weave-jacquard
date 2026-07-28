"""Bounded logical accounting for live Jacquard artifact stores."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .errors import ValidationError

ARTIFACT_STORAGE_REPORT_FORMAT = "weave-artifact-storage-report-v1"
ARTIFACT_STORAGE_ROOT_ID_FORMAT = "weave-artifact-storage-root-v1"
MAX_ARTIFACT_STORAGE_ROOTS = 16
MAX_ARTIFACT_SCAN_ENTRIES = 1_000_000
MAX_ARTIFACT_SCAN_DEPTH = 64


class ArtifactStorageService:
    """Measure complete logical usage without following links or double counting roots."""

    def __init__(self, roots: Mapping[str, str | Path]) -> None:
        if not isinstance(roots, Mapping) or not roots:
            raise ValueError("artifact roots must be a non-empty mapping")
        if len(roots) > MAX_ARTIFACT_STORAGE_ROOTS:
            raise ValueError(
                f"artifact roots exceed the limit {MAX_ARTIFACT_STORAGE_ROOTS}"
            )

        normalized: dict[str, Path] = {}
        for name, value in roots.items():
            if not isinstance(name, str) or not name:
                raise ValueError("artifact root names must be non-empty strings")
            if name in normalized:
                raise ValueError(f"duplicate artifact root name {name!r}")
            normalized[name] = Path(value).resolve()
        self.roots = normalized

    def report(self) -> dict[str, Any]:
        """Return one complete path-redacted logical storage snapshot."""

        return self._report(excluded_paths=())

    def _report(
        self,
        *,
        excluded_paths: Iterable[str | Path],
    ) -> dict[str, Any]:
        """Return accounting while omitting exact internal reservation subtrees."""

        self._validate_distinct_roots()
        internal_exclusions = {Path(path).resolve() for path in excluded_paths}
        entries_remaining = MAX_ARTIFACT_SCAN_ENTRIES
        families: list[dict[str, Any]] = []
        for name in sorted(self.roots):
            path = self.roots[name]
            nested = {
                other_name: other_path
                for other_name, other_path in self.roots.items()
                if other_name != name and self._is_descendant(other_path, path)
            }
            skipped_paths = set(nested.values())
            skipped_paths.update(
                candidate
                for candidate in internal_exclusions
                if self._is_descendant(candidate, path)
            )
            family, entries_remaining = self._scan_root(
                name,
                path,
                nested_root_names=sorted(nested),
                skipped_paths=skipped_paths,
                entries_remaining=entries_remaining,
            )
            families.append(family)

        aggregate = {
            "logical_bytes": sum(item["logical_bytes"] for item in families),
            "regular_files": sum(item["regular_files"] for item in families),
            "directories": sum(item["directories"] for item in families),
            "symlinks": sum(item["symlinks"] for item in families),
            "special_entries": sum(item["special_entries"] for item in families),
            "entries_scanned": sum(item["entries_scanned"] for item in families),
            "root_count": len(families),
        }
        payload = {
            "format": ARTIFACT_STORAGE_REPORT_FORMAT,
            "complete": True,
            "accounting": "logical-path-bytes",
            "nested_root_policy": "most-specific-root-owns-subtree",
            "aggregate": aggregate,
            "families": families,
            "limits": {
                "roots": MAX_ARTIFACT_STORAGE_ROOTS,
                "entries": MAX_ARTIFACT_SCAN_ENTRIES,
                "depth": MAX_ARTIFACT_SCAN_DEPTH,
            },
        }
        return {
            **payload,
            "storage_snapshot_id": self._hash_json(payload),
        }

    def _validate_distinct_roots(self) -> None:
        by_path: dict[Path, list[str]] = {}
        for name, path in self.roots.items():
            by_path.setdefault(path, []).append(name)
        conflicts = [sorted(names) for names in by_path.values() if len(names) > 1]
        if conflicts:
            raise ValidationError(
                "ARTIFACT_STORAGE_ROOT_CONFLICT",
                "artifact families resolve to the same storage root: "
                + ", ".join("/".join(names) for names in sorted(conflicts)),
            )

    def _scan_root(
        self,
        name: str,
        root: Path,
        *,
        nested_root_names: list[str],
        skipped_paths: set[Path],
        entries_remaining: int,
    ) -> tuple[dict[str, Any], int]:
        try:
            root_stat = root.lstat()
        except OSError as exc:
            raise ValidationError(
                "ARTIFACT_STORAGE_ROOT_UNAVAILABLE",
                f"artifact storage root {name!r} is unavailable",
            ) from exc
        if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
            raise ValidationError(
                "ARTIFACT_STORAGE_ROOT_INVALID",
                f"artifact storage root {name!r} must be a non-symlink directory",
            )

        logical_bytes = 0
        regular_files = 0
        directories = 1
        symlinks = 0
        special_entries = 0
        entries_scanned = 0
        largest_file_bytes = 0
        stack: list[tuple[Path, int]] = [(root, 0)]

        while stack:
            directory, depth = stack.pop()
            try:
                with os.scandir(directory) as iterator:
                    for entry in iterator:
                        if entries_remaining <= 0:
                            raise ValidationError(
                                "ARTIFACT_STORAGE_SCAN_LIMIT_EXCEEDED",
                                "artifact storage exceeds the bounded scan entry limit "
                                f"{MAX_ARTIFACT_SCAN_ENTRIES}",
                            )
                        entries_remaining -= 1
                        entries_scanned += 1
                        entry_path = Path(entry.path)
                        if entry_path in skipped_paths:
                            continue
                        try:
                            entry_stat = entry.stat(follow_symlinks=False)
                        except OSError as exc:
                            raise ValidationError(
                                "ARTIFACT_STORAGE_SCAN_FAILED",
                                f"artifact storage family {name!r} changed during scan",
                            ) from exc
                        mode = entry_stat.st_mode
                        if stat.S_ISLNK(mode):
                            symlinks += 1
                        elif stat.S_ISDIR(mode):
                            if depth >= MAX_ARTIFACT_SCAN_DEPTH:
                                raise ValidationError(
                                    "ARTIFACT_STORAGE_DEPTH_EXCEEDED",
                                    "artifact storage exceeds the bounded directory depth "
                                    f"{MAX_ARTIFACT_SCAN_DEPTH}",
                                )
                            directories += 1
                            stack.append((entry_path, depth + 1))
                        elif stat.S_ISREG(mode):
                            regular_files += 1
                            logical_bytes += entry_stat.st_size
                            largest_file_bytes = max(
                                largest_file_bytes,
                                entry_stat.st_size,
                            )
                        else:
                            special_entries += 1
            except ValidationError:
                raise
            except OSError as exc:
                raise ValidationError(
                    "ARTIFACT_STORAGE_SCAN_FAILED",
                    f"cannot enumerate artifact storage family {name!r}",
                ) from exc

        return (
            {
                "family": name,
                "root_id": self._root_id(name, root),
                "logical_bytes": logical_bytes,
                "regular_files": regular_files,
                "directories": directories,
                "symlinks": symlinks,
                "special_entries": special_entries,
                "entries_scanned": entries_scanned,
                "largest_file_bytes": largest_file_bytes,
                "nested_roots": nested_root_names,
            },
            entries_remaining,
        )

    @staticmethod
    def _is_descendant(candidate: Path, parent: Path) -> bool:
        try:
            candidate.relative_to(parent)
        except ValueError:
            return False
        return candidate != parent

    @staticmethod
    def _root_id(name: str, path: Path) -> str:
        encoded = (
            ARTIFACT_STORAGE_ROOT_ID_FORMAT.encode("utf-8")
            + b"\0"
            + name.encode("utf-8")
            + b"\0"
            + str(path).encode("utf-8")
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
    "ARTIFACT_STORAGE_REPORT_FORMAT",
    "ARTIFACT_STORAGE_ROOT_ID_FORMAT",
    "MAX_ARTIFACT_SCAN_DEPTH",
    "MAX_ARTIFACT_SCAN_ENTRIES",
    "MAX_ARTIFACT_STORAGE_ROOTS",
    "ArtifactStorageService",
]
