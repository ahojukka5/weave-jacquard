"""Deterministic bounded inventory for retained artifact family roots."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ArtifactIntegrityError, NotFoundError, ValidationError

RETAINED_ARTIFACT_INVENTORY_FORMAT = "weave-retained-artifact-inventory-v1"
RETAINED_ARTIFACT_ROOT_ID_FORMAT = "weave-retained-artifact-root-v1"
RETAINED_ARTIFACT_ENTRY_ID_FORMAT = "weave-retained-artifact-entry-v1"

RETAINED_ARTIFACT_FAMILIES = (
    "candidate_builds",
    "candidate_test_qualifications",
    "committed_builds",
    "database_backups",
    "test_batches",
    "test_runs",
    "tested_merge_attestations",
)

MAX_RECONCILIATION_FAMILIES = 16
MAX_RECONCILIATION_ENTRIES = 1_000_000
MAX_RECONCILIATION_ENTRIES_PER_FAMILY = 250_000
MAX_RECONCILIATION_EXAMPLES = 25

_CLASSIFICATIONS = (
    "verified",
    "corrupt",
    "staging",
    "quarantined",
    "lock_internal",
    "unknown",
)


@dataclass(frozen=True)
class RetainedArtifactFamily:
    """One retained family root plus its production verifier and ID contract."""

    name: str
    root: Path
    artifact_id_pattern: re.Pattern[str]
    verifier: Callable[[str], Mapping[str, Any]]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("retained artifact family name must be non-empty")
        if not isinstance(self.artifact_id_pattern, re.Pattern):
            raise TypeError("artifact_id_pattern must be a compiled regular expression")
        if not callable(self.verifier):
            raise TypeError("retained artifact verifier must be callable")
        object.__setattr__(self, "root", Path(self.root).absolute())


@dataclass(frozen=True, order=True)
class _EntrySnapshot:
    name: str
    mode: int
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int


class RetainedArtifactInventoryService:
    """Classify complete family-root membership without following links."""

    def __init__(
        self,
        families: Iterable[RetainedArtifactFamily],
        *,
        max_entries: int = MAX_RECONCILIATION_ENTRIES,
        max_entries_per_family: int = MAX_RECONCILIATION_ENTRIES_PER_FAMILY,
        max_examples: int = MAX_RECONCILIATION_EXAMPLES,
    ) -> None:
        ordered = tuple(families)
        if not ordered:
            raise ValueError("at least one retained artifact family is required")
        if len(ordered) > MAX_RECONCILIATION_FAMILIES:
            raise ValueError(
                f"retained artifact families exceed the limit {MAX_RECONCILIATION_FAMILIES}"
            )
        self._validate_positive_limit("max_entries", max_entries)
        self._validate_positive_limit(
            "max_entries_per_family",
            max_entries_per_family,
        )
        self._validate_positive_limit("max_examples", max_examples)

        by_name: dict[str, RetainedArtifactFamily] = {}
        by_root: dict[Path, list[str]] = {}
        for family in ordered:
            if not isinstance(family, RetainedArtifactFamily):
                raise TypeError("families must contain RetainedArtifactFamily instances")
            if family.name in by_name:
                raise ValueError(f"duplicate retained artifact family {family.name!r}")
            by_name[family.name] = family
            by_root.setdefault(family.root, []).append(family.name)

        conflicts = [sorted(names) for names in by_root.values() if len(names) > 1]
        if conflicts:
            raise ValidationError(
                "ARTIFACT_RECONCILIATION_ROOT_CONFLICT",
                "retained artifact families use the same root: "
                + ", ".join("/".join(names) for names in sorted(conflicts)),
            )

        self.families = tuple(by_name[name] for name in sorted(by_name))
        self.max_entries = max_entries
        self.max_entries_per_family = max_entries_per_family
        self.max_examples = max_examples

    def report(self) -> dict[str, Any]:
        """Return complete path-redacted inventory and stable membership identity."""

        entries_remaining = self.max_entries
        family_reports: list[dict[str, Any]] = []
        identity_families: list[dict[str, Any]] = []

        for family in self.families:
            snapshots = self._snapshot_entries(
                family,
                remaining=entries_remaining,
            )
            entries_remaining -= len(snapshots)
            nested = self._nested_family_names(family)
            skipped_roots = {
                candidate.root for candidate in self.families if candidate.name in nested
            }
            records = [
                self._classify(family, snapshot)
                for snapshot in snapshots
                if family.root / snapshot.name not in skipped_roots
            ]
            after = self._snapshot_entries(
                family,
                remaining=self.max_entries,
            )
            if snapshots != after:
                raise ValidationError(
                    "ARTIFACT_RECONCILIATION_CHANGED_DURING_SCAN",
                    f"retained artifact family {family.name!r} changed during scan",
                )

            family_report, family_identity = self._family_report(
                family,
                records,
                entries_scanned=len(snapshots),
                nested_roots=nested,
            )
            family_reports.append(family_report)
            identity_families.append(family_identity)

        aggregate_counts = {
            classification: sum(family["counts"][classification] for family in family_reports)
            for classification in _CLASSIFICATIONS
        }
        aggregate = {
            "family_count": len(family_reports),
            "entry_count": sum(family["entry_count"] for family in family_reports),
            "entries_scanned": sum(family["entries_scanned"] for family in family_reports),
            "counts": aggregate_counts,
        }
        payload = {
            "format": RETAINED_ARTIFACT_INVENTORY_FORMAT,
            "complete": True,
            "aggregate": aggregate,
            "families": family_reports,
            "limits": {
                "families": MAX_RECONCILIATION_FAMILIES,
                "entries": self.max_entries,
                "entries_per_family": self.max_entries_per_family,
                "examples_per_classification": self.max_examples,
            },
        }
        identity_payload = {
            "format": RETAINED_ARTIFACT_INVENTORY_FORMAT,
            "families": identity_families,
        }
        return {
            **payload,
            "inventory_id": self._hash_json(identity_payload),
        }

    def _snapshot_entries(
        self,
        family: RetainedArtifactFamily,
        *,
        remaining: int,
    ) -> tuple[_EntrySnapshot, ...]:
        root = family.root
        try:
            root_stat = root.lstat()
        except OSError as exc:
            raise ValidationError(
                "ARTIFACT_RECONCILIATION_ROOT_UNAVAILABLE",
                f"retained artifact root {family.name!r} is unavailable",
            ) from exc
        if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
            raise ValidationError(
                "ARTIFACT_RECONCILIATION_ROOT_INVALID",
                f"retained artifact root {family.name!r} must be a non-symlink directory",
            )

        snapshots: list[_EntrySnapshot] = []
        try:
            with os.scandir(root) as iterator:
                for entry in iterator:
                    if len(snapshots) >= self.max_entries_per_family or len(snapshots) >= remaining:
                        raise ValidationError(
                            "ARTIFACT_RECONCILIATION_SCAN_LIMIT_EXCEEDED",
                            "retained artifact inventory exceeds its bounded entry limit",
                        )
                    try:
                        entry_stat = entry.stat(follow_symlinks=False)
                    except OSError as exc:
                        raise ValidationError(
                            "ARTIFACT_RECONCILIATION_SCAN_FAILED",
                            f"retained artifact family {family.name!r} changed during enumeration",
                        ) from exc
                    snapshots.append(
                        _EntrySnapshot(
                            name=entry.name,
                            mode=entry_stat.st_mode,
                            device=entry_stat.st_dev,
                            inode=entry_stat.st_ino,
                            size=entry_stat.st_size,
                            mtime_ns=entry_stat.st_mtime_ns,
                            ctime_ns=entry_stat.st_ctime_ns,
                        )
                    )
        except ValidationError:
            raise
        except OSError as exc:
            raise ValidationError(
                "ARTIFACT_RECONCILIATION_SCAN_FAILED",
                f"cannot enumerate retained artifact family {family.name!r}",
            ) from exc
        return tuple(sorted(snapshots))

    def _classify(
        self,
        family: RetainedArtifactFamily,
        snapshot: _EntrySnapshot,
    ) -> dict[str, Any]:
        entry_type = self._entry_type(snapshot.mode)
        artifact_id = snapshot.name if family.artifact_id_pattern.fullmatch(snapshot.name) else None
        entry_id = self._entry_id(
            family.name,
            self._root_id(family),
            snapshot.name,
        )

        if entry_type in {"symlink", "special"}:
            return self._entry_record(
                entry_id=entry_id,
                artifact_id=artifact_id,
                entry_type=entry_type,
                classification="unknown",
            )

        internal = self._internal_classification(snapshot.name)
        if internal is not None:
            return self._entry_record(
                entry_id=entry_id,
                artifact_id=artifact_id,
                entry_type=entry_type,
                classification=internal,
            )

        if artifact_id is None:
            return self._entry_record(
                entry_id=entry_id,
                artifact_id=None,
                entry_type=entry_type,
                classification="unknown",
            )
        if entry_type != "directory":
            return self._entry_record(
                entry_id=entry_id,
                artifact_id=artifact_id,
                entry_type=entry_type,
                classification="corrupt",
                error_code="ARTIFACT_ENTRY_NOT_DIRECTORY",
            )

        try:
            verified = family.verifier(artifact_id)
            if not isinstance(verified, Mapping):
                raise TypeError("artifact verifier must return a mapping")
        except Exception as exc:
            return self._entry_record(
                entry_id=entry_id,
                artifact_id=artifact_id,
                entry_type=entry_type,
                classification="corrupt",
                error_code=self._error_code(exc),
            )
        return self._entry_record(
            entry_id=entry_id,
            artifact_id=artifact_id,
            entry_type=entry_type,
            classification="verified",
        )

    def _family_report(
        self,
        family: RetainedArtifactFamily,
        records: list[dict[str, Any]],
        *,
        entries_scanned: int,
        nested_roots: list[str],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        counts = {
            classification: sum(record["classification"] == classification for record in records)
            for classification in _CLASSIFICATIONS
        }
        examples = {
            classification: [
                self._public_entry(record)
                for record in records
                if record["classification"] == classification
            ][: self.max_examples]
            for classification in _CLASSIFICATIONS
        }
        root_id = self._root_id(family)
        identity_entries = [
            {key: value for key, value in record.items() if value is not None} for record in records
        ]
        identity = {
            "family": family.name,
            "root_id": root_id,
            "nested_roots": nested_roots,
            "entries": identity_entries,
        }
        report = {
            "family": family.name,
            "root_id": root_id,
            "complete": True,
            "entry_count": len(records),
            "entries_scanned": entries_scanned,
            "nested_roots": nested_roots,
            "counts": counts,
            "examples": examples,
            "family_catalog_id": self._hash_json(identity),
        }
        return report, identity

    def _nested_family_names(
        self,
        family: RetainedArtifactFamily,
    ) -> list[str]:
        return [
            candidate.name
            for candidate in self.families
            if candidate.name != family.name and self._is_descendant(candidate.root, family.root)
        ]

    @staticmethod
    def _entry_record(
        *,
        entry_id: str,
        artifact_id: str | None,
        entry_type: str,
        classification: str,
        error_code: str | None = None,
    ) -> dict[str, Any]:
        return {
            "entry_id": entry_id,
            "artifact_id": artifact_id,
            "entry_type": entry_type,
            "classification": classification,
            "error_code": error_code,
        }

    @staticmethod
    def _public_entry(record: Mapping[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in record.items() if value is not None}

    @staticmethod
    def _entry_type(mode: int) -> str:
        if stat.S_ISLNK(mode):
            return "symlink"
        if stat.S_ISDIR(mode):
            return "directory"
        if stat.S_ISREG(mode):
            return "regular_file"
        return "special"

    @staticmethod
    def _internal_classification(name: str) -> str | None:
        if ".replaced-" in name or ".quarantine-" in name:
            return "quarantined"
        if name.endswith(".lock") or name.startswith(".lock-"):
            return "lock_internal"
        if name.startswith("."):
            return "staging"
        return None

    @staticmethod
    def _error_code(exc: Exception) -> str:
        if isinstance(exc, ValidationError):
            return exc.code
        if isinstance(exc, ArtifactIntegrityError):
            return "ARTIFACT_INTEGRITY_ERROR"
        if isinstance(exc, NotFoundError):
            return "NOT_FOUND"
        if isinstance(exc, OSError):
            return "OS_ERROR"
        if isinstance(exc, TypeError):
            return "INVALID_ARTIFACT_VERIFIER_RESULT"
        return type(exc).__name__

    @staticmethod
    def _is_descendant(candidate: Path, parent: Path) -> bool:
        try:
            candidate.relative_to(parent)
        except ValueError:
            return False
        return candidate != parent

    @staticmethod
    def _root_id(family: RetainedArtifactFamily) -> str:
        return RetainedArtifactInventoryService._hash_parts(
            RETAINED_ARTIFACT_ROOT_ID_FORMAT,
            family.name,
            str(family.root),
        )

    @staticmethod
    def _entry_id(family: str, root_id: str, name: str) -> str:
        return RetainedArtifactInventoryService._hash_parts(
            RETAINED_ARTIFACT_ENTRY_ID_FORMAT,
            family,
            root_id,
            name,
        )

    @staticmethod
    def _hash_parts(*parts: str) -> str:
        return hashlib.sha256(b"\0".join(part.encode("utf-8") for part in parts)).hexdigest()

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

    @staticmethod
    def _validate_positive_limit(name: str, value: Any) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")


__all__ = [
    "MAX_RECONCILIATION_ENTRIES",
    "MAX_RECONCILIATION_ENTRIES_PER_FAMILY",
    "MAX_RECONCILIATION_EXAMPLES",
    "MAX_RECONCILIATION_FAMILIES",
    "RETAINED_ARTIFACT_ENTRY_ID_FORMAT",
    "RETAINED_ARTIFACT_FAMILIES",
    "RETAINED_ARTIFACT_INVENTORY_FORMAT",
    "RETAINED_ARTIFACT_ROOT_ID_FORMAT",
    "RetainedArtifactFamily",
    "RetainedArtifactInventoryService",
]
