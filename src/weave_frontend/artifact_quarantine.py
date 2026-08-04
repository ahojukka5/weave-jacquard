"""Guarded single-entry publication into retained-artifact quarantine."""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .artifact_quarantine_contract import (
    ARTIFACT_QUARANTINE_FORMAT,
    ARTIFACT_QUARANTINE_INTENT_FORMAT,
    build_intent,
    build_manifest,
    quarantine_identities,
    validate_intent,
    validate_quarantine_request,
    verify_relocation,
)
from .artifact_quarantine_io import ArtifactQuarantineIO
from .artifact_quarantine_state import ArtifactQuarantineState
from .artifact_retention import ArtifactRetentionPlanner
from .artifact_retention_accounting import ArtifactRetentionAccountant
from .artifact_retention_catalog import ArtifactRetentionCatalog
from .artifact_retention_policy import hash_json
from .errors import ValidationError


class ArtifactQuarantineService:
    """Move one exact plan entry into verifiable family-local quarantine."""

    def __init__(self, reconciliation: Any) -> None:
        if not hasattr(reconciliation, "inventory"):
            raise TypeError(
                "reconciliation must expose its retained artifact inventory"
            )
        self.reconciliation = reconciliation
        self.catalog = ArtifactRetentionCatalog(reconciliation)
        self.state = ArtifactQuarantineState(reconciliation)
        self.io = ArtifactQuarantineIO(reconciliation)

    def quarantine(
        self,
        policy: Mapping[str, Any],
        plan: Mapping[str, Any],
        *,
        entry_id: str,
        quarantined_at_unix_ns: int | None = None,
    ) -> dict[str, Any]:
        """Publish one selected entry without deleting quarantined content."""

        normalized_policy, normalized_plan, selected = (
            validate_quarantine_request(
                self.reconciliation,
                policy,
                plan,
                entry_id=entry_id,
            )
        )
        quarantine_id, quarantine_entry_id = quarantine_identities(
            normalized_plan,
            selected,
        )
        final_name = f".quarantine-{quarantine_entry_id}"
        staging_name = f"{final_name}.staging"
        journal_path = self.io.journal_path(quarantine_id)

        with self.io.lock(self.io.control_lock_path(quarantine_id)):
            intent = self.io.read_optional_metadata(journal_path)
            if intent is None:
                intent = self._create_intent(
                    normalized_policy,
                    normalized_plan,
                    selected,
                    quarantine_id=quarantine_id,
                    quarantine_entry_id=quarantine_entry_id,
                    final_name=final_name,
                    staging_name=staging_name,
                    quarantined_at_unix_ns=quarantined_at_unix_ns,
                )
                self.io.write_metadata(journal_path, intent)
            validate_intent(
                intent,
                policy=normalized_policy,
                plan=normalized_plan,
                entry=selected,
                quarantine_id=quarantine_id,
                quarantine_entry_id=quarantine_entry_id,
                final_name=final_name,
                staging_name=staging_name,
            )

            family = self._family(intent["family"])
            source_lock = family.root / intent["source_lock_name"]
            with self.io.lock(source_lock):
                if not intent["source_lock_was_present"]:
                    self.io.fsync_directory(family.root)
                self.state.verify_normalized(intent)
                result = self._continue_publication(intent, family.root)
                self.state.verify_normalized(intent)
                return result

    def _create_intent(
        self,
        policy: Mapping[str, Any],
        plan: Mapping[str, Any],
        selected: Mapping[str, Any],
        *,
        quarantine_id: str,
        quarantine_entry_id: str,
        final_name: str,
        staging_name: str,
        quarantined_at_unix_ns: int | None,
    ) -> dict[str, Any]:
        before = self.state.snapshot(plan["reconciliation_id"])
        regenerated = ArtifactRetentionPlanner(
            self.reconciliation,
            max_plan_entries=plan["limits"]["selected_entries"],
            max_scan_entries=plan["limits"]["scan_entries"],
            max_scan_depth=plan["limits"]["scan_depth"],
        ).plan(
            policy,
            as_of_unix_ns=plan["as_of_unix_ns"],
        )
        if regenerated != dict(plan):
            raise ValidationError(
                "ARTIFACT_QUARANTINE_STALE_PLAN",
                "retention plan no longer reproduces from current state",
            )

        reconciliation_id, entries, locations = self.catalog.snapshot(
            plan["reconciliation_id"]
        )
        if reconciliation_id != plan["reconciliation_id"]:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_STALE_PLAN",
                "selected plan reconciliation is no longer current",
            )
        catalog_entry = next(
            (
                entry
                for entry in entries
                if entry["entry_id"] == selected["entry_id"]
            ),
            None,
        )
        if catalog_entry is None:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_SOURCE_CHANGED",
                "selected plan entry is absent from the live catalog",
            )
        self._verify_catalog_entry(selected, catalog_entry)
        self.catalog.verify_unchanged(reconciliation_id, locations)

        after = self.state.snapshot(plan["reconciliation_id"])
        if (
            before["database_snapshot_id"] != after["database_snapshot_id"]
            or before["inventory_id"] != after["inventory_id"]
            or before["catalog_state_id"] != after["catalog_state_id"]
        ):
            raise ValidationError(
                "ARTIFACT_QUARANTINE_STATE_CHANGED",
                "artifact state changed while preparing quarantine intent",
            )

        source = Path(catalog_entry["path"])
        family = self._family(selected["family"])
        if source.parent != family.root:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_SOURCE_INVALID",
                "selected source is not a direct member of its family root",
            )
        original_name = source.name
        source_lock_name = f".{original_name}.lock"
        source_lock_entry_id = self.reconciliation.inventory._entry_id(
            family.name,
            self.reconciliation.inventory._root_id(family),
            source_lock_name,
        )
        source_lock_was_present = self.state.source_lock_was_present(
            after,
            family.name,
            source_lock_entry_id,
        )
        capture, _remaining = self._accountant(plan["limits"]).capture(
            source,
            plan["limits"]["scan_entries"],
        )
        self._verify_source_capture(selected, capture)
        final_state = self.state.snapshot(plan["reconciliation_id"])
        if final_state["catalog_state_id"] != after["catalog_state_id"]:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_STATE_CHANGED",
                "artifact state changed while snapshotting the selected source",
            )

        timestamp = (
            time.time_ns()
            if quarantined_at_unix_ns is None
            else quarantined_at_unix_ns
        )
        if (
            isinstance(timestamp, bool)
            or not isinstance(timestamp, int)
            or not 0 <= timestamp <= 2**63 - 1
        ):
            raise ValidationError(
                "ARTIFACT_QUARANTINE_TIMESTAMP_INVALID",
                "quarantined_at_unix_ns must be a non-negative signed 64-bit integer",
            )
        identity = {
            "format": ARTIFACT_QUARANTINE_INTENT_FORMAT,
            "quarantine_id": quarantine_id,
            "quarantine_entry_id": quarantine_entry_id,
            "plan_id": plan["plan_id"],
            "plan_document_id": hash_json(plan),
            "reconciliation_id": plan["reconciliation_id"],
            "policy_id": plan["policy_id"],
            "family": family.name,
            "original_name": original_name,
            "source_lock_name": source_lock_name,
            "source_lock_entry_id": source_lock_entry_id,
            "source_lock_was_present": source_lock_was_present,
            "final_name": final_name,
            "staging_name": staging_name,
            "quarantined_at_unix_ns": timestamp,
            "plan_entry": dict(selected),
            "plan_limits": dict(plan["limits"]),
            "database_snapshot_id": final_state["database_snapshot_id"],
            "inventory_id": final_state["inventory_id"],
            "catalog_state_id": final_state["catalog_state_id"],
            "original_identity_record": self.state.identity_record(
                final_state,
                family.name,
                selected["entry_id"],
            ),
            "original_location_record": self.state.location_record(
                final_state,
                selected["entry_id"],
            ),
            "original_root_record": self.state.root_record(
                final_state,
                family.name,
            ),
            "source_capture": capture,
        }
        return build_intent(identity)

    def _continue_publication(
        self,
        intent: Mapping[str, Any],
        family_root: Path,
    ) -> dict[str, Any]:
        source = family_root / intent["original_name"]
        staging = family_root / intent["staging_name"]
        final = family_root / intent["final_name"]

        if os.path.lexists(final):
            if os.path.lexists(staging) or os.path.lexists(source):
                raise ValidationError(
                    "ARTIFACT_QUARANTINE_STATE_INVALID",
                    "completed quarantine conflicts with a live source or staging capsule",
                )
            self.io.fsync_directory(family_root)
            return self._verify_capsule(final, intent)

        self.io.ensure_staging(staging)
        capsule_intent = staging / "quarantine-intent.json"
        self.io.write_metadata(capsule_intent, intent)
        payload = staging / "payload"
        source_exists = os.path.lexists(source)
        payload_exists = os.path.lexists(payload)
        if source_exists == payload_exists:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_STATE_INVALID",
                "quarantine requires exactly one live source or staged payload",
            )

        if source_exists:
            capture, _remaining = self._accountant(intent["plan_limits"]).capture(
                source,
                intent["plan_limits"]["scan_entries"],
            )
            self._verify_source_capture(intent["plan_entry"], capture)
            verify_relocation(intent["source_capture"], capture)
            try:
                os.replace(source, payload)
            except OSError as exc:
                raise ValidationError(
                    "ARTIFACT_QUARANTINE_MOVE_FAILED",
                    "cannot atomically move the selected entry into quarantine",
                ) from exc
            self.io.fsync_directory(family_root)
            self.io.fsync_directory(staging)

        quarantined, _remaining = self._accountant(
            intent["plan_limits"]
        ).capture(
            payload,
            intent["plan_limits"]["scan_entries"],
        )
        verify_relocation(intent["source_capture"], quarantined)
        manifest = build_manifest(intent, quarantined)
        self.io.write_metadata(staging / "quarantine-manifest.json", manifest)
        self._verify_capsule(staging, intent)

        if os.path.lexists(final):
            raise ValidationError(
                "ARTIFACT_QUARANTINE_STATE_INVALID",
                "final quarantine capsule appeared during publication",
            )
        try:
            os.replace(staging, final)
        except OSError as exc:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_PUBLICATION_FAILED",
                "cannot publish the verified quarantine capsule",
            ) from exc
        self.io.fsync_directory(family_root)
        return self._verify_capsule(final, intent)

    def _verify_capsule(
        self,
        capsule: Path,
        intent: Mapping[str, Any],
    ) -> dict[str, Any]:
        self.io.require_directory(capsule)
        try:
            with os.scandir(capsule) as iterator:
                names = sorted(item.name for item in iterator)
        except OSError as exc:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_CAPSULE_UNAVAILABLE",
                "cannot enumerate the quarantine capsule",
            ) from exc
        if names != [
            "payload",
            "quarantine-intent.json",
            "quarantine-manifest.json",
        ]:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_CAPSULE_INVALID",
                "quarantine capsule has unexpected top-level entries",
            )
        stored_intent = self.io.read_metadata(
            capsule / "quarantine-intent.json"
        )
        if stored_intent != dict(intent):
            raise ValidationError(
                "ARTIFACT_QUARANTINE_METADATA_INVALID",
                "capsule intent differs from the durable quarantine journal",
            )
        payload = capsule / "payload"
        capture, _remaining = self._accountant(intent["plan_limits"]).capture(
            payload,
            intent["plan_limits"]["scan_entries"],
        )
        verify_relocation(intent["source_capture"], capture)
        expected_manifest = build_manifest(intent, capture)
        manifest = self.io.read_metadata(
            capsule / "quarantine-manifest.json"
        )
        if manifest != expected_manifest:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_METADATA_INVALID",
                "quarantine manifest does not match the verified payload",
            )
        entry = intent["plan_entry"]
        result = {
            "format": ARTIFACT_QUARANTINE_FORMAT,
            "complete": True,
            "mutation": "quarantine",
            "deletion": "none",
            "restorable": True,
            "quarantine_id": intent["quarantine_id"],
            "quarantine_entry_id": intent["quarantine_entry_id"],
            "manifest_id": manifest["manifest_id"],
            "intent_id": intent["intent_id"],
            "plan_id": intent["plan_id"],
            "reconciliation_id": intent["reconciliation_id"],
            "policy_id": intent["policy_id"],
            "family": intent["family"],
            "original_entry_id": entry["entry_id"],
            "original_classification": entry["classification"],
            "original_entry_type": entry["entry_type"],
            "quarantined_at_unix_ns": intent["quarantined_at_unix_ns"],
            "payload": {
                name: capture[name]
                for name in (
                    "logical_bytes",
                    "regular_files",
                    "directories",
                    "symlinks",
                    "special_entries",
                    "entries_scanned",
                    "entry_snapshot_id",
                    "relocation_snapshot_id",
                )
            },
        }
        if "artifact_id" in entry:
            result["artifact_id"] = entry["artifact_id"]
        return result

    @staticmethod
    def _verify_catalog_entry(
        selected: Mapping[str, Any],
        catalog_entry: Mapping[str, Any],
    ) -> None:
        for name in (
            "family",
            "classification",
            "entry_id",
            "entry_type",
        ):
            if catalog_entry.get(name) != selected.get(name):
                raise ValidationError(
                    "ARTIFACT_QUARANTINE_SOURCE_CHANGED",
                    "live catalog entry differs from the selected plan entry",
                )
        if catalog_entry.get("artifact_id") != selected.get("artifact_id"):
            raise ValidationError(
                "ARTIFACT_QUARANTINE_SOURCE_CHANGED",
                "live artifact identity differs from the selected plan entry",
            )

    @staticmethod
    def _verify_source_capture(
        selected: Mapping[str, Any],
        capture: Mapping[str, Any],
    ) -> None:
        expected = (
            "logical_bytes",
            "regular_files",
            "directories",
            "symlinks",
            "special_entries",
            "entries_scanned",
            "entry_snapshot_id",
        )
        if any(capture[name] != selected[name] for name in expected):
            raise ValidationError(
                "ARTIFACT_QUARANTINE_SOURCE_CHANGED",
                "selected source differs from the exact retention plan snapshot",
            )

    def _accountant(
        self,
        limits: Mapping[str, Any],
    ) -> ArtifactRetentionAccountant:
        return ArtifactRetentionAccountant(
            self.reconciliation.inventory,
            max_scan_entries=limits["scan_entries"],
            max_scan_depth=limits["scan_depth"],
        )

    def _family(self, name: str) -> Any:
        for family in self.reconciliation.inventory.families:
            if family.name == name:
                return family
        raise ValidationError(
            "ARTIFACT_QUARANTINE_FAMILY_INVALID",
            "selected quarantine family is not configured",
        )


__all__ = ["ArtifactQuarantineService"]
