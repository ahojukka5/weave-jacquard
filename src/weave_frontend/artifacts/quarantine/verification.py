"""Exact verification and holding-period evidence for quarantine capsules."""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ...artifact_retention_accounting import ArtifactRetentionAccountant
from ...artifact_retention_policy import hash_json, is_sha256
from ...errors import ValidationError
from .io import ArtifactQuarantineIO
from .restoration_contract import (
    validate_stored_manifest,
    validate_stored_quarantine_intent,
    verify_payload_against_manifest,
)
from .state import ArtifactQuarantineState

ARTIFACT_QUARANTINE_VERIFICATION_FORMAT = "weave-artifact-quarantine-verification-v1"
ARTIFACT_QUARANTINE_DELETE_AUTHORIZATION_FORMAT = (
    "weave-artifact-quarantine-delete-authorization-v1"
)
_MAX_UNIX_NS = 2**63 - 1


class ArtifactQuarantineVerificationService:
    """Reverify one exact capsule and enforce its operator holding period."""

    def __init__(self, reconciliation: Any) -> None:
        if not hasattr(reconciliation, "inventory"):
            raise TypeError("reconciliation must expose its retained artifact inventory")
        self.reconciliation = reconciliation
        self.io = ArtifactQuarantineIO(reconciliation)
        self.state = ArtifactQuarantineState(reconciliation)

    def verify(
        self,
        *,
        quarantine_id: str,
        manifest_id: str,
        plan_id: str,
        minimum_holding_seconds: int,
        as_of_unix_ns: int | None = None,
    ) -> dict[str, Any]:
        """Return path-redacted exact evidence that deletion may be requested."""

        self._require_sha256("quarantine_id", quarantine_id)
        self._require_sha256("manifest_id", manifest_id)
        self._require_sha256("plan_id", plan_id)
        self._require_nonnegative_int(
            "minimum_holding_seconds",
            minimum_holding_seconds,
        )
        as_of = time.time_ns() if as_of_unix_ns is None else as_of_unix_ns
        self._require_unix_ns("as_of_unix_ns", as_of)

        with self.io.lock(self.io.control_lock_path(quarantine_id)):
            intent = self.load_intent(
                quarantine_id=quarantine_id,
                plan_id=plan_id,
            )
            family = self.family(intent["family"])
            with self.io.lock(family.root / intent["source_lock_name"]):
                return self.verify_locked(
                    intent,
                    family,
                    manifest_id=manifest_id,
                    minimum_holding_seconds=minimum_holding_seconds,
                    as_of_unix_ns=as_of,
                )

    def load_intent(
        self,
        *,
        quarantine_id: str,
        plan_id: str,
    ) -> dict[str, Any]:
        """Load the exact durable quarantine journal for a later locked action."""

        intent = validate_stored_quarantine_intent(
            self.io.read_metadata(self.io.journal_path(quarantine_id)),
            quarantine_id=quarantine_id,
        )
        if intent["plan_id"] != plan_id:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_PLAN_ID_MISMATCH",
                "quarantine journal does not match the exact retention plan",
            )
        return intent

    def verify_locked(
        self,
        intent: Mapping[str, Any],
        family: Any,
        *,
        manifest_id: str,
        minimum_holding_seconds: int,
        as_of_unix_ns: int,
    ) -> dict[str, Any]:
        """Verify a capsule while its control and source locks are already held."""

        before = self.state.snapshot()
        self._require_live_quarantine(before, intent, family)
        manifest, capture = self._verify_capsule(
            family.root,
            intent,
            manifest_id,
        )
        after = self.state.snapshot()
        for name in (
            "database_snapshot_id",
            "inventory_id",
            "catalog_state_id",
            "reconciliation_id",
        ):
            if before[name] != after[name]:
                raise ValidationError(
                    "ARTIFACT_QUARANTINE_VERIFICATION_STATE_CHANGED",
                    "artifact state changed while verifying quarantine",
                )
        self._require_live_quarantine(after, intent, family)

        holding_ns = minimum_holding_seconds * 1_000_000_000
        if holding_ns > _MAX_UNIX_NS:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_HOLDING_PERIOD_INVALID",
                "minimum holding period exceeds signed 64-bit nanoseconds",
            )
        eligible_at = intent["quarantined_at_unix_ns"] + holding_ns
        if eligible_at > _MAX_UNIX_NS:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_HOLDING_PERIOD_INVALID",
                "quarantine holding deadline exceeds signed 64-bit time",
            )
        if as_of_unix_ns < eligible_at:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_HOLDING_PERIOD_NOT_MET",
                "quarantine has not completed the required holding period",
            )

        entry = intent["plan_entry"]
        authorization = {
            "format": ARTIFACT_QUARANTINE_DELETE_AUTHORIZATION_FORMAT,
            "quarantine_id": intent["quarantine_id"],
            "quarantine_entry_id": intent["quarantine_entry_id"],
            "quarantine_intent_id": intent["intent_id"],
            "manifest_id": manifest["manifest_id"],
            "plan_id": intent["plan_id"],
            "database_snapshot_id": after["database_snapshot_id"],
            "family": intent["family"],
            "original_entry_id": entry["entry_id"],
            "artifact_id": entry.get("artifact_id"),
            "original_classification": entry["classification"],
            "original_entry_type": entry["entry_type"],
            "quarantined_at_unix_ns": intent["quarantined_at_unix_ns"],
            "minimum_holding_seconds": minimum_holding_seconds,
            "eligible_at_unix_ns": eligible_at,
            "as_of_unix_ns": as_of_unix_ns,
            "payload": dict(capture),
        }
        report = {
            "format": ARTIFACT_QUARANTINE_VERIFICATION_FORMAT,
            "complete": True,
            "mutation": "none",
            "deletion_eligible": True,
            **{
                name: authorization[name]
                for name in (
                    "quarantine_id",
                    "quarantine_entry_id",
                    "quarantine_intent_id",
                    "manifest_id",
                    "plan_id",
                    "database_snapshot_id",
                    "family",
                    "original_entry_id",
                    "artifact_id",
                    "original_classification",
                    "original_entry_type",
                    "quarantined_at_unix_ns",
                    "minimum_holding_seconds",
                    "eligible_at_unix_ns",
                    "as_of_unix_ns",
                    "payload",
                )
            },
            "reconciliation_id": after["reconciliation_id"],
            "inventory_id": after["inventory_id"],
            "catalog_state_id": after["catalog_state_id"],
            "verification_id": hash_json(authorization),
        }
        return report

    def _verify_capsule(
        self,
        family_root: Path,
        intent: Mapping[str, Any],
        manifest_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        capsule = family_root / intent["final_name"]
        names = self._capsule_names(capsule)
        if names != [
            "payload",
            "quarantine-intent.json",
            "quarantine-manifest.json",
        ]:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_VERIFICATION_CAPSULE_INVALID",
                "quarantine capsule is incomplete or has unexpected entries",
            )
        stored_intent = self.io.read_metadata(capsule / "quarantine-intent.json")
        if stored_intent != dict(intent):
            raise ValidationError(
                "ARTIFACT_QUARANTINE_VERIFICATION_METADATA_INVALID",
                "capsule intent differs from the durable quarantine journal",
            )
        manifest = validate_stored_manifest(
            self.io.read_metadata(capsule / "quarantine-manifest.json"),
            intent=intent,
            manifest_id=manifest_id,
        )
        limits = intent["plan_limits"]
        capture, _remaining = ArtifactRetentionAccountant(
            self.reconciliation.inventory,
            max_scan_entries=limits["scan_entries"],
            max_scan_depth=limits["scan_depth"],
        ).capture(capsule / "payload", limits["scan_entries"])
        verify_payload_against_manifest(intent, manifest, capture)
        return manifest, capture

    def _require_live_quarantine(
        self,
        snapshot: Mapping[str, Any],
        intent: Mapping[str, Any],
        family: Any,
    ) -> None:
        root_id = self.reconciliation.inventory._root_id(family)
        capsule_entry_id = self.reconciliation.inventory._entry_id(
            family.name,
            root_id,
            intent["final_name"],
        )
        record = self.state.optional_identity_record(
            snapshot,
            family.name,
            capsule_entry_id,
        )
        if (
            record is None
            or record.get("classification") != "quarantined"
            or record.get("entry_type") != "directory"
        ):
            raise ValidationError(
                "ARTIFACT_QUARANTINE_VERIFICATION_STATE_INVALID",
                "exact quarantine capsule is absent from current reconciliation",
            )

        artifact_id = intent["plan_entry"].get("artifact_id")
        if artifact_id is None:
            return
        for family_record in snapshot["identity_families"]:
            for candidate in family_record["records"]:
                if candidate.get("artifact_id") == artifact_id and candidate.get(
                    "classification"
                ) in {"reachable", "missing"}:
                    raise ValidationError(
                        "ARTIFACT_QUARANTINE_REQUIRED_EVIDENCE",
                        "current database state requires the quarantined artifact",
                    )

    def _capsule_names(self, capsule: Path) -> list[str]:
        self.io.require_directory(capsule)
        try:
            with os.scandir(capsule) as iterator:
                return sorted(item.name for item in iterator)
        except OSError as exc:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_VERIFICATION_CAPSULE_UNAVAILABLE",
                "cannot enumerate the quarantine capsule",
            ) from exc

    def family(self, name: str) -> Any:
        for family in self.reconciliation.inventory.families:
            if family.name == name:
                return family
        raise ValidationError(
            "ARTIFACT_QUARANTINE_VERIFICATION_FAMILY_INVALID",
            "quarantine family is not configured",
        )

    @staticmethod
    def _require_sha256(name: str, value: Any) -> None:
        if not is_sha256(value):
            raise ValidationError(
                "ARTIFACT_QUARANTINE_VERIFICATION_ID_INVALID",
                f"{name} must be 64 lowercase hexadecimal characters",
            )

    @staticmethod
    def _require_nonnegative_int(name: str, value: Any) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_HOLDING_PERIOD_INVALID",
                f"{name} must be a non-negative integer",
            )

    @classmethod
    def _require_unix_ns(cls, name: str, value: Any) -> None:
        cls._require_nonnegative_int(name, value)
        if value > _MAX_UNIX_NS:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_HOLDING_PERIOD_INVALID",
                f"{name} exceeds signed 64-bit time",
            )


__all__ = [
    "ARTIFACT_QUARANTINE_DELETE_AUTHORIZATION_FORMAT",
    "ARTIFACT_QUARANTINE_VERIFICATION_FORMAT",
    "ArtifactQuarantineVerificationService",
]
