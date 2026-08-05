"""Verified, idempotent restore from retained-artifact quarantine."""

from __future__ import annotations

import os
import stat
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ...artifact_retention_accounting import ArtifactRetentionAccountant
from ...errors import ValidationError
from .io import ArtifactQuarantineIO
from .restoration_contract import (
    build_restore_intent,
    build_restore_result,
    restore_identities,
    validate_restore_intent,
    validate_restore_result,
    validate_stored_manifest,
    validate_stored_quarantine_intent,
    verify_payload_against_manifest,
    verify_restored_payload,
    verify_result_payload,
)


class ArtifactQuarantineRestoreService:
    """Restore one exact verified quarantine capsule to its original name."""

    def __init__(self, reconciliation: Any) -> None:
        if not hasattr(reconciliation, "inventory"):
            raise TypeError("reconciliation must expose its retained artifact inventory")
        self.reconciliation = reconciliation
        self.io = ArtifactQuarantineIO(reconciliation)

    def restore(
        self,
        *,
        quarantine_id: str,
        manifest_id: str,
        restored_at_unix_ns: int | None = None,
    ) -> dict[str, Any]:
        """Restore one capsule without overwriting any live retained entry."""

        restore_id = restore_identities(quarantine_id, manifest_id)
        restore_intent_path = self.io.control_root / (f"{restore_id}.restore-intent.json")
        restore_result_path = self.io.control_root / (f"{restore_id}.restore-result.json")
        with self.io.lock(self.io.control_lock_path(quarantine_id)):
            quarantine_intent = validate_stored_quarantine_intent(
                self.io.read_metadata(self.io.journal_path(quarantine_id)),
                quarantine_id=quarantine_id,
            )
            family = self._family(quarantine_intent["family"])
            source_lock = family.root / quarantine_intent["source_lock_name"]
            with self.io.lock(source_lock):
                stored_restore_intent = self.io.read_optional_metadata(restore_intent_path)
                if stored_restore_intent is None:
                    self._verify_ready_capsule(
                        family.root,
                        quarantine_intent,
                        manifest_id,
                    )
                    destination = family.root / quarantine_intent["original_name"]
                    if os.path.lexists(destination):
                        raise ValidationError(
                            "ARTIFACT_QUARANTINE_RESTORE_DESTINATION_EXISTS",
                            "original retained entry name is already occupied",
                        )
                    timestamp = (
                        time.time_ns() if restored_at_unix_ns is None else restored_at_unix_ns
                    )
                    restore_intent = build_restore_intent(
                        quarantine_intent,
                        manifest_id=manifest_id,
                        restore_id=restore_id,
                        restored_at_unix_ns=timestamp,
                    )
                    self.io.write_metadata(restore_intent_path, restore_intent)
                else:
                    restore_intent = validate_restore_intent(
                        stored_restore_intent,
                        quarantine_intent=quarantine_intent,
                        manifest_id=manifest_id,
                        restore_id=restore_id,
                    )

                stored_result = self.io.read_optional_metadata(restore_result_path)
                if stored_result is not None:
                    result = validate_restore_result(
                        stored_result,
                        restore_intent=restore_intent,
                    )
                    capture = self._verify_completed_restore(
                        family.root,
                        restore_intent,
                    )
                    verify_result_payload(result, capture)
                    self._cleanup_capsule(family.root / restore_intent["capsule_name"])
                    return result

                result = self._continue_restore(
                    family.root,
                    quarantine_intent,
                    restore_intent,
                    manifest_id,
                )
                self.io.write_metadata(restore_result_path, result)
                self._cleanup_capsule(family.root / restore_intent["capsule_name"])
                return result

    def _continue_restore(
        self,
        family_root: Path,
        quarantine_intent: Mapping[str, Any],
        restore_intent: Mapping[str, Any],
        manifest_id: str,
    ) -> dict[str, Any]:
        capsule = family_root / restore_intent["capsule_name"]
        destination = family_root / restore_intent["original_name"]
        payload = capsule / "payload"
        destination_exists = os.path.lexists(destination)
        payload_exists = os.path.lexists(payload)
        if destination_exists and payload_exists:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_RESTORE_STATE_INVALID",
                "restore has both a live destination and quarantined payload",
            )
        if not destination_exists and not payload_exists:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_RESTORE_STATE_INVALID",
                "restore has neither a live destination nor quarantined payload",
            )

        if payload_exists:
            self._verify_ready_capsule(
                family_root,
                quarantine_intent,
                manifest_id,
            )
            if os.path.lexists(destination):
                raise ValidationError(
                    "ARTIFACT_QUARANTINE_RESTORE_DESTINATION_EXISTS",
                    "original retained entry name appeared during restore",
                )
            try:
                os.replace(payload, destination)
            except OSError as exc:
                raise ValidationError(
                    "ARTIFACT_QUARANTINE_RESTORE_MOVE_FAILED",
                    "cannot atomically restore the quarantined payload",
                ) from exc
            self.io.fsync_directory(family_root)
            self.io.fsync_directory(capsule)
        else:
            self._verify_metadata_only_capsule(
                capsule,
                quarantine_intent,
                manifest_id,
            )

        restored_capture = self._capture(destination, restore_intent)
        verify_restored_payload(restore_intent, restored_capture)
        return build_restore_result(restore_intent, restored_capture)

    def _verify_ready_capsule(
        self,
        family_root: Path,
        quarantine_intent: Mapping[str, Any],
        manifest_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        capsule = family_root / quarantine_intent["final_name"]
        names = self._capsule_names(capsule)
        if names != [
            "payload",
            "quarantine-intent.json",
            "quarantine-manifest.json",
        ]:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_RESTORE_CAPSULE_INVALID",
                "quarantine capsule is incomplete or has unexpected entries",
            )
        stored_intent = self.io.read_metadata(capsule / "quarantine-intent.json")
        if stored_intent != dict(quarantine_intent):
            raise ValidationError(
                "ARTIFACT_QUARANTINE_RESTORE_METADATA_INVALID",
                "capsule intent differs from the durable quarantine journal",
            )
        manifest = validate_stored_manifest(
            self.io.read_metadata(capsule / "quarantine-manifest.json"),
            intent=quarantine_intent,
            manifest_id=manifest_id,
        )
        capture = self._capture(
            capsule / "payload",
            {"plan_limits": quarantine_intent["plan_limits"]},
        )
        verify_payload_against_manifest(quarantine_intent, manifest, capture)
        return manifest, capture

    def _verify_metadata_only_capsule(
        self,
        capsule: Path,
        quarantine_intent: Mapping[str, Any],
        manifest_id: str,
    ) -> None:
        names = self._capsule_names(capsule)
        if names != ["quarantine-intent.json", "quarantine-manifest.json"]:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_RESTORE_CAPSULE_INVALID",
                "interrupted restore capsule has unexpected entries",
            )
        stored_intent = self.io.read_metadata(capsule / "quarantine-intent.json")
        if stored_intent != dict(quarantine_intent):
            raise ValidationError(
                "ARTIFACT_QUARANTINE_RESTORE_METADATA_INVALID",
                "capsule intent differs from the durable quarantine journal",
            )
        validate_stored_manifest(
            self.io.read_metadata(capsule / "quarantine-manifest.json"),
            intent=quarantine_intent,
            manifest_id=manifest_id,
        )

    def _verify_completed_restore(
        self,
        family_root: Path,
        restore_intent: Mapping[str, Any],
    ) -> dict[str, Any]:
        destination = family_root / restore_intent["original_name"]
        if not os.path.lexists(destination):
            raise ValidationError(
                "ARTIFACT_QUARANTINE_RESTORE_STATE_INVALID",
                "completed restored payload is unavailable",
            )
        capture = self._capture(destination, restore_intent)
        verify_restored_payload(restore_intent, capture)
        return capture

    def _cleanup_capsule(self, capsule: Path) -> None:
        if not os.path.lexists(capsule):
            return
        names = self._capsule_names(capsule)
        expected = {"quarantine-intent.json", "quarantine-manifest.json"}
        if any(name not in expected for name in names):
            raise ValidationError(
                "ARTIFACT_QUARANTINE_RESTORE_CAPSULE_INVALID",
                "restored capsule cannot be cleaned safely",
            )
        for name in names:
            path = capsule / name
            try:
                metadata = path.lstat()
            except OSError as exc:
                raise ValidationError(
                    "ARTIFACT_QUARANTINE_RESTORE_CLEANUP_FAILED",
                    "cannot inspect restored capsule metadata",
                ) from exc
            if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                raise ValidationError(
                    "ARTIFACT_QUARANTINE_RESTORE_CLEANUP_FAILED",
                    "restored capsule metadata must be regular files",
                )
            try:
                path.unlink()
            except OSError as exc:
                raise ValidationError(
                    "ARTIFACT_QUARANTINE_RESTORE_CLEANUP_FAILED",
                    "cannot remove restored capsule metadata",
                ) from exc
        self.io.fsync_directory(capsule)
        try:
            capsule.rmdir()
        except OSError as exc:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_RESTORE_CLEANUP_FAILED",
                "cannot remove the empty restored capsule",
            ) from exc
        self.io.fsync_directory(capsule.parent)

    def _capture(
        self,
        path: Path,
        value: Mapping[str, Any],
    ) -> dict[str, Any]:
        limits = value["plan_limits"]
        accountant = ArtifactRetentionAccountant(
            self.reconciliation.inventory,
            max_scan_entries=limits["scan_entries"],
            max_scan_depth=limits["scan_depth"],
        )
        capture, _remaining = accountant.capture(
            path,
            limits["scan_entries"],
        )
        return capture

    def _capsule_names(self, capsule: Path) -> list[str]:
        self.io.require_directory(capsule)
        try:
            with os.scandir(capsule) as iterator:
                return sorted(item.name for item in iterator)
        except OSError as exc:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_RESTORE_CAPSULE_UNAVAILABLE",
                "cannot enumerate the quarantine capsule",
            ) from exc

    def _family(self, name: str) -> Any:
        for family in self.reconciliation.inventory.families:
            if family.name == name:
                return family
        raise ValidationError(
            "ARTIFACT_QUARANTINE_RESTORE_FAMILY_INVALID",
            "quarantine family is not configured",
        )


__all__ = ["ArtifactQuarantineRestoreService"]
