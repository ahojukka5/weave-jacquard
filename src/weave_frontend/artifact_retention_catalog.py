"""Complete path-private catalog adapter for retention planning."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .artifact_reachability import ARTIFACT_RECONCILIATION_FORMAT
from .artifact_retention_policy import entry_order
from .errors import ValidationError


class ArtifactRetentionCatalog:
    """Rebuild complete reconciliation records and bind them to live paths."""

    def __init__(self, reconciliation: Any) -> None:
        self.reconciliation = reconciliation

    def snapshot(
        self,
        expected_reconciliation_id: str,
    ) -> tuple[str, tuple[dict[str, Any], ...], dict[str, tuple[Any, ...]]]:
        """Return exact reconciled records plus one private top-level snapshot."""

        database = self.reconciliation._database_snapshot()
        inventory = self.reconciliation._inventory_snapshot()
        after = self.reconciliation._database_snapshot()
        if database.report["database_snapshot_id"] != after.report["database_snapshot_id"]:
            raise ValidationError(
                "ARTIFACT_RETENTION_STALE_RECONCILIATION",
                "database changed while rebuilding reconciliation evidence",
            )
        report = self.reconciliation._reconcile(database, inventory)
        families = report.pop("_identity_families")
        reconciliation_id = self.reconciliation._hash_json(
            {
                "format": ARTIFACT_RECONCILIATION_FORMAT,
                "database_snapshot_id": database.report["database_snapshot_id"],
                "inventory_id": inventory.report["inventory_id"],
                "families": families,
            }
        )
        if reconciliation_id != expected_reconciliation_id:
            raise ValidationError(
                "ARTIFACT_RETENTION_STALE_RECONCILIATION",
                "policy does not reference the current complete reconciliation",
            )
        records = tuple(record for family in families for record in family["records"])
        locations = self.locations()
        return reconciliation_id, self._join(records, locations), locations

    def locations(self) -> dict[str, tuple[Any, ...]]:
        """Return complete top-level metadata keyed by opaque entry identity."""

        inventory = self.reconciliation.inventory
        remaining = inventory.max_entries
        result: dict[str, tuple[Any, ...]] = {}
        for family in inventory.families:
            snapshots = inventory._snapshot_entries(family, remaining=remaining)
            remaining -= len(snapshots)
            nested = inventory._nested_family_names(family)
            skipped = {
                candidate.root for candidate in inventory.families if candidate.name in nested
            }
            root_id = inventory._root_id(family)
            for snapshot in snapshots:
                path = family.root / snapshot.name
                if path in skipped:
                    continue
                entry_id = inventory._entry_id(family.name, root_id, snapshot.name)
                if entry_id in result:
                    raise ValidationError(
                        "ARTIFACT_RETENTION_CATALOG_INVALID",
                        "catalog contains duplicate entry identities",
                    )
                result[entry_id] = (
                    family.name,
                    path,
                    snapshot.mode,
                    snapshot.device,
                    snapshot.inode,
                    snapshot.size,
                    snapshot.mtime_ns,
                    snapshot.ctime_ns,
                )
        return result

    def verify_unchanged(
        self,
        expected_reconciliation_id: str,
        locations: Mapping[str, tuple[Any, ...]],
    ) -> None:
        """Reject top-level or reconciliation changes observed during planning."""

        if dict(locations) != self.locations():
            raise ValidationError(
                "ARTIFACT_RETENTION_CATALOG_CHANGED",
                "retained artifact entries changed during retention planning",
            )
        final = self.reconciliation.report()
        if (
            final.get("complete") is not True
            or final.get("reconciliation_id") != expected_reconciliation_id
        ):
            raise ValidationError(
                "ARTIFACT_RETENTION_STALE_RECONCILIATION",
                "reconciliation changed during retention planning",
            )

    def _join(
        self,
        records: tuple[dict[str, Any], ...],
        locations: Mapping[str, tuple[Any, ...]],
    ) -> tuple[dict[str, Any], ...]:
        joined = []
        for record in records:
            if record.get("entry_type") == "missing":
                continue
            location = locations.get(record.get("entry_id"))
            if location is None or location[0] != record.get("family"):
                raise ValidationError(
                    "ARTIFACT_RETENTION_CATALOG_CHANGED",
                    "reconciliation entry is absent from the current roots",
                )
            entry_type = self.reconciliation.inventory._entry_type(location[2])
            if entry_type != record.get("entry_type"):
                raise ValidationError(
                    "ARTIFACT_RETENTION_CATALOG_CHANGED",
                    "reconciliation entry type changed during planning",
                )
            joined.append(
                {
                    "family": location[0],
                    "path": Path(location[1]),
                    "mtime_ns": location[6],
                    "entry_id": record["entry_id"],
                    "artifact_id": record.get("artifact_id"),
                    "entry_type": entry_type,
                    "classification": record["classification"],
                }
            )
        return tuple(sorted(joined, key=entry_order))


__all__ = ["ArtifactRetentionCatalog"]
