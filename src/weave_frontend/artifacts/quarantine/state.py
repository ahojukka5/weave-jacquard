"""Normalized retry-state verification for guarded artifact quarantine."""

from __future__ import annotations

import copy
import os
import stat
from collections.abc import Mapping
from typing import Any

from ...artifact_reachability import ARTIFACT_RECONCILIATION_FORMAT
from ...artifact_retention_policy import hash_json
from ...errors import ValidationError

ARTIFACT_QUARANTINE_CATALOG_FORMAT = "weave-artifact-quarantine-catalog-v1"


class ArtifactQuarantineState:
    """Capture exact private state and normalize only executor-owned mutations."""

    def __init__(self, reconciliation: Any) -> None:
        self.reconciliation = reconciliation
        self.inventory = reconciliation.inventory

    def snapshot(
        self,
        expected_reconciliation_id: str | None = None,
    ) -> dict[str, Any]:
        """Return one stable reconciliation and top-level filesystem snapshot."""

        database_before = self.reconciliation._database_snapshot()
        inventory = self.reconciliation._inventory_snapshot()
        database_after = self.reconciliation._database_snapshot()
        database_id = database_before.report["database_snapshot_id"]
        if database_id != database_after.report["database_snapshot_id"]:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_STATE_CHANGED",
                "database changed while capturing quarantine state",
            )
        report = self.reconciliation._reconcile(database_before, inventory)
        identity_families = report.pop("_identity_families")
        reconciliation_id = self.reconciliation._hash_json(
            {
                "format": ARTIFACT_RECONCILIATION_FORMAT,
                "database_snapshot_id": database_id,
                "inventory_id": inventory.report["inventory_id"],
                "families": identity_families,
            }
        )
        if (
            expected_reconciliation_id is not None
            and reconciliation_id != expected_reconciliation_id
        ):
            raise ValidationError(
                "ARTIFACT_QUARANTINE_STALE_PLAN",
                "quarantine request does not match the current reconciliation",
            )

        root_records, location_records = self._catalog_records()
        roots_after, locations_after = self._catalog_records()
        if root_records != roots_after or location_records != locations_after:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_STATE_CHANGED",
                "artifact roots changed while capturing quarantine state",
            )
        catalog_state_id = self._catalog_state_id(
            root_records,
            location_records,
        )
        return {
            "database_snapshot_id": database_id,
            "inventory_id": inventory.report["inventory_id"],
            "reconciliation_id": reconciliation_id,
            "identity_families": identity_families,
            "root_records": root_records,
            "location_records": location_records,
            "catalog_state_id": catalog_state_id,
        }

    def identity_record(
        self,
        snapshot: Mapping[str, Any],
        family: str,
        entry_id: str,
    ) -> dict[str, Any]:
        record = self.optional_identity_record(snapshot, family, entry_id)
        if record is None:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_SOURCE_CHANGED",
                "selected entry is absent from the captured reconciliation",
            )
        return record

    @staticmethod
    def optional_identity_record(
        snapshot: Mapping[str, Any],
        family: str,
        entry_id: str,
    ) -> dict[str, Any] | None:
        for family_record in snapshot["identity_families"]:
            if family_record["family"] != family:
                continue
            for record in family_record["records"]:
                if record["entry_id"] == entry_id:
                    return copy.deepcopy(record)
        return None

    @staticmethod
    def location_record(
        snapshot: Mapping[str, Any],
        entry_id: str,
    ) -> dict[str, Any]:
        for record in snapshot["location_records"]:
            if record["entry_id"] == entry_id:
                return copy.deepcopy(record)
        raise ValidationError(
            "ARTIFACT_QUARANTINE_SOURCE_CHANGED",
            "selected entry is absent from the captured artifact roots",
        )

    @staticmethod
    def root_record(
        snapshot: Mapping[str, Any],
        family: str,
    ) -> dict[str, Any]:
        for record in snapshot["root_records"]:
            if record["family"] == family:
                return copy.deepcopy(record)
        raise ValidationError(
            "ARTIFACT_QUARANTINE_STATE_INVALID",
            "selected family root is absent from quarantine state",
        )

    def source_lock_was_present(
        self,
        snapshot: Mapping[str, Any],
        family: str,
        lock_entry_id: str,
    ) -> bool:
        location = next(
            (
                record
                for record in snapshot["location_records"]
                if record["entry_id"] == lock_entry_id
            ),
            None,
        )
        identity = self.optional_identity_record(snapshot, family, lock_entry_id)
        if location is None and identity is None:
            return False
        if location is None or identity is None:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_LOCK_INVALID",
                "source publication lock has inconsistent reconciliation state",
            )
        if (
            identity.get("classification") != "lock_internal"
            or identity.get("entry_type") != "regular_file"
            or not stat.S_ISREG(location["mode"])
        ):
            raise ValidationError(
                "ARTIFACT_QUARANTINE_LOCK_INVALID",
                "source publication lock must be a regular internal lock entry",
            )
        return True

    def verify_normalized(self, intent: Mapping[str, Any]) -> None:
        """Reject all changes except this operation's known source relocation."""

        current = self.snapshot()
        if current["database_snapshot_id"] != intent["database_snapshot_id"]:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_STALE_PLAN",
                "database reachability changed after quarantine intent",
            )

        removed = {
            intent["plan_entry"]["entry_id"],
            self._entry_id(intent["family"], intent["staging_name"]),
            self._entry_id(intent["family"], intent["final_name"]),
        }
        if not intent["source_lock_was_present"]:
            removed.add(intent["source_lock_entry_id"])

        normalized_families = copy.deepcopy(current["identity_families"])
        selected_current = self.optional_identity_record(
            current,
            intent["family"],
            intent["plan_entry"]["entry_id"],
        )
        if selected_current is not None and selected_current != intent["original_identity_record"]:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_SOURCE_CHANGED",
                "selected reconciliation evidence changed after quarantine intent",
            )
        self._validate_executor_records(current, intent)
        target = self._family(normalized_families, intent["family"])
        target["records"] = [
            record for record in target["records"] if record["entry_id"] not in removed
        ]
        target["records"].append(copy.deepcopy(intent["original_identity_record"]))
        target["records"].sort(key=self.identity_order)

        reconstructed = self.reconciliation._hash_json(
            {
                "format": ARTIFACT_RECONCILIATION_FORMAT,
                "database_snapshot_id": intent["database_snapshot_id"],
                "inventory_id": intent["inventory_id"],
                "families": normalized_families,
            }
        )
        if reconstructed != intent["reconciliation_id"]:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_STALE_PLAN",
                "artifact reconciliation changed outside this quarantine operation",
            )

        normalized_locations = [
            copy.deepcopy(record)
            for record in current["location_records"]
            if record["entry_id"] not in removed
        ]
        current_source = next(
            (
                record
                for record in current["location_records"]
                if record["entry_id"] == intent["plan_entry"]["entry_id"]
            ),
            None,
        )
        if current_source is not None and current_source != intent["original_location_record"]:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_SOURCE_CHANGED",
                "selected top-level entry changed after quarantine intent",
            )
        normalized_locations.append(copy.deepcopy(intent["original_location_record"]))
        normalized_locations.sort(key=self.location_order)

        normalized_roots = copy.deepcopy(current["root_records"])
        target_root = next(
            record for record in normalized_roots if record["family"] == intent["family"]
        )
        original_root = intent["original_root_record"]
        for name in ("size", "mtime_ns", "ctime_ns"):
            target_root[name] = original_root[name]
        catalog_state_id = self._catalog_state_id(
            normalized_roots,
            normalized_locations,
        )
        if catalog_state_id != intent["catalog_state_id"]:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_STALE_PLAN",
                "artifact roots changed outside this quarantine operation",
            )

    @staticmethod
    def identity_order(item: Mapping[str, Any]) -> tuple[str, str, str]:
        return (
            str(item["classification"]),
            str(item.get("artifact_id") or ""),
            str(item["entry_id"]),
        )

    @staticmethod
    def location_order(item: Mapping[str, Any]) -> tuple[str, str]:
        return (str(item["family"]), str(item["entry_id"]))

    def _validate_executor_records(
        self,
        current: Mapping[str, Any],
        intent: Mapping[str, Any],
    ) -> None:
        expected = {
            self._entry_id(intent["family"], intent["staging_name"]): "quarantined",
            self._entry_id(intent["family"], intent["final_name"]): "quarantined",
        }
        if not intent["source_lock_was_present"]:
            expected[intent["source_lock_entry_id"]] = "lock_internal"
        for entry_id, classification in expected.items():
            record = self.optional_identity_record(
                current,
                intent["family"],
                entry_id,
            )
            if record is not None and record.get("classification") != classification:
                raise ValidationError(
                    "ARTIFACT_QUARANTINE_STATE_INVALID",
                    "executor-owned quarantine entry has an unexpected classification",
                )

    def _catalog_records(
        self,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        remaining = self.inventory.max_entries
        roots: list[dict[str, Any]] = []
        locations: list[dict[str, Any]] = []
        for family in self.inventory.families:
            try:
                before = family.root.lstat()
                snapshots = self.inventory._snapshot_entries(
                    family,
                    remaining=remaining,
                )
                remaining -= len(snapshots)
                after = family.root.lstat()
            except ValidationError:
                raise
            except OSError as exc:
                raise ValidationError(
                    "ARTIFACT_QUARANTINE_STATE_UNAVAILABLE",
                    "cannot capture an artifact family root",
                ) from exc
            if self._stat_identity(before) != self._stat_identity(after):
                raise ValidationError(
                    "ARTIFACT_QUARANTINE_STATE_CHANGED",
                    "artifact family root changed while capturing quarantine state",
                )
            roots.append(
                {
                    "family": family.name,
                    "root_id": self.inventory._root_id(family),
                    **self._stat_record(before),
                }
            )
            nested = self.inventory._nested_family_names(family)
            skipped = {
                candidate.root for candidate in self.inventory.families if candidate.name in nested
            }
            root_id = self.inventory._root_id(family)
            for snapshot in snapshots:
                if family.root / snapshot.name in skipped:
                    continue
                locations.append(
                    {
                        "family": family.name,
                        "entry_id": self.inventory._entry_id(
                            family.name,
                            root_id,
                            snapshot.name,
                        ),
                        "mode": snapshot.mode,
                        "device": snapshot.device,
                        "inode": snapshot.inode,
                        "size": snapshot.size,
                        "mtime_ns": snapshot.mtime_ns,
                        "ctime_ns": snapshot.ctime_ns,
                    }
                )
        roots.sort(key=lambda item: item["family"])
        locations.sort(key=self.location_order)
        return roots, locations

    @staticmethod
    def _stat_record(value: os.stat_result) -> dict[str, int]:
        return {
            "mode": value.st_mode,
            "device": value.st_dev,
            "inode": value.st_ino,
            "size": value.st_size,
            "mtime_ns": value.st_mtime_ns,
            "ctime_ns": value.st_ctime_ns,
        }

    @classmethod
    def _stat_identity(cls, value: os.stat_result) -> tuple[int, ...]:
        record = cls._stat_record(value)
        return tuple(record[name] for name in sorted(record))

    @staticmethod
    def _catalog_state_id(
        roots: list[dict[str, Any]],
        locations: list[dict[str, Any]],
    ) -> str:
        return hash_json(
            {
                "format": ARTIFACT_QUARANTINE_CATALOG_FORMAT,
                "roots": roots,
                "locations": locations,
            }
        )

    def _entry_id(self, family_name: str, name: str) -> str:
        family = next(family for family in self.inventory.families if family.name == family_name)
        return self.inventory._entry_id(
            family_name,
            self.inventory._root_id(family),
            name,
        )

    @staticmethod
    def _family(
        families: list[dict[str, Any]],
        name: str,
    ) -> dict[str, Any]:
        for family in families:
            if family["family"] == name:
                return family
        raise ValidationError(
            "ARTIFACT_QUARANTINE_STATE_INVALID",
            "selected family is absent from quarantine state",
        )


__all__ = [
    "ARTIFACT_QUARANTINE_CATALOG_FORMAT",
    "ArtifactQuarantineState",
]
