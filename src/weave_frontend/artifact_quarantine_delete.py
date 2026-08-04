"""Guarded, journaled permanent deletion of verified quarantine capsules."""

from __future__ import annotations

import os
import stat
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .artifact_quarantine_io import ArtifactQuarantineIO
from .artifact_quarantine_state import ArtifactQuarantineState
from .artifact_quarantine_verification import (
    ArtifactQuarantineVerificationService,
)
from .artifact_retention_policy import hash_json, is_sha256
from .errors import ValidationError

ARTIFACT_QUARANTINE_DELETE_FORMAT = "weave-artifact-quarantine-delete-v1"
ARTIFACT_QUARANTINE_DELETE_INTENT_FORMAT = (
    "weave-artifact-quarantine-delete-intent-v1"
)
ARTIFACT_QUARANTINE_DELETE_RESULT_FORMAT = (
    "weave-artifact-quarantine-delete-result-v1"
)
_MAX_UNIX_NS = 2**63 - 1

_DELETE_INTENT_KEYS = {
    "format",
    "delete_id",
    "quarantine_id",
    "quarantine_entry_id",
    "quarantine_intent_id",
    "manifest_id",
    "plan_id",
    "verification_id",
    "verification_reconciliation_id",
    "database_snapshot_id",
    "family",
    "capsule_name",
    "source_lock_name",
    "original_entry_id",
    "artifact_id",
    "original_classification",
    "original_entry_type",
    "minimum_holding_seconds",
    "as_of_unix_ns",
    "deleted_at_unix_ns",
    "plan_limits",
    "payload",
    "delete_intent_id",
}
_DELETE_RESULT_KEYS = {
    "format",
    "complete",
    "mutation",
    "deletion",
    "restorable",
    "delete_id",
    "delete_result_id",
    "delete_intent_id",
    "quarantine_id",
    "quarantine_entry_id",
    "quarantine_intent_id",
    "manifest_id",
    "plan_id",
    "verification_id",
    "family",
    "original_entry_id",
    "artifact_id",
    "original_classification",
    "original_entry_type",
    "deleted_at_unix_ns",
    "logical_bytes_reclaimed",
    "payload_entries_deleted",
}


class ArtifactQuarantineDeleteService:
    """Permanently delete one exact held capsule without following links."""

    def __init__(self, reconciliation: Any) -> None:
        if not hasattr(reconciliation, "inventory"):
            raise TypeError(
                "reconciliation must expose its retained artifact inventory"
            )
        self.reconciliation = reconciliation
        self.io = ArtifactQuarantineIO(reconciliation)
        self.state = ArtifactQuarantineState(reconciliation)
        self.verifier = ArtifactQuarantineVerificationService(reconciliation)

    def delete(
        self,
        *,
        quarantine_id: str,
        manifest_id: str,
        plan_id: str,
        verification_id: str,
        minimum_holding_seconds: int,
        as_of_unix_ns: int,
        deleted_at_unix_ns: int | None = None,
    ) -> dict[str, Any]:
        """Delete one exact verified capsule and return durable completion evidence."""

        for name, value in (
            ("quarantine_id", quarantine_id),
            ("manifest_id", manifest_id),
            ("plan_id", plan_id),
            ("verification_id", verification_id),
        ):
            self._require_sha256(name, value)
        self._require_nonnegative_int(
            "minimum_holding_seconds",
            minimum_holding_seconds,
        )
        self._require_unix_ns("as_of_unix_ns", as_of_unix_ns)
        timestamp = time.time_ns() if deleted_at_unix_ns is None else deleted_at_unix_ns
        self._require_unix_ns("deleted_at_unix_ns", timestamp)

        delete_id = hash_json(
            {
                "format": ARTIFACT_QUARANTINE_DELETE_FORMAT,
                "quarantine_id": quarantine_id,
                "manifest_id": manifest_id,
                "plan_id": plan_id,
                "verification_id": verification_id,
            }
        )
        intent_path = self.io.control_root / f"{delete_id}.delete-intent.json"
        result_path = self.io.control_root / f"{delete_id}.delete-result.json"

        with self.io.lock(self.io.control_lock_path(quarantine_id)):
            quarantine_intent = self.verifier.load_intent(
                quarantine_id=quarantine_id,
                plan_id=plan_id,
            )
            family = self.verifier.family(quarantine_intent["family"])
            with self.io.lock(family.root / quarantine_intent["source_lock_name"]):
                stored_intent = self.io.read_optional_metadata(intent_path)
                if stored_intent is None:
                    verification = self.verifier.verify_locked(
                        quarantine_intent,
                        family,
                        manifest_id=manifest_id,
                        minimum_holding_seconds=minimum_holding_seconds,
                        as_of_unix_ns=as_of_unix_ns,
                    )
                    if verification["verification_id"] != verification_id:
                        raise ValidationError(
                            "ARTIFACT_QUARANTINE_DELETE_VERIFICATION_MISMATCH",
                            "delete request does not match exact verification evidence",
                        )
                    delete_intent = self._build_intent(
                        quarantine_intent,
                        verification,
                        delete_id=delete_id,
                        deleted_at_unix_ns=timestamp,
                    )
                    self.io.write_metadata(intent_path, delete_intent)
                else:
                    delete_intent = self._validate_intent(
                        stored_intent,
                        quarantine_intent=quarantine_intent,
                        delete_id=delete_id,
                        manifest_id=manifest_id,
                        plan_id=plan_id,
                        verification_id=verification_id,
                        minimum_holding_seconds=minimum_holding_seconds,
                        as_of_unix_ns=as_of_unix_ns,
                    )
                    current = self.state.snapshot()
                    if (
                        current["database_snapshot_id"]
                        != delete_intent["database_snapshot_id"]
                    ):
                        raise ValidationError(
                            "ARTIFACT_QUARANTINE_DELETE_DATABASE_CHANGED",
                            "database changed after permanent-delete intent",
                        )

                stored_result = self.io.read_optional_metadata(result_path)
                if stored_result is not None:
                    result = self._validate_result(
                        stored_result,
                        delete_intent=delete_intent,
                    )
                    capsule = family.root / delete_intent["capsule_name"]
                    if os.path.lexists(capsule):
                        raise ValidationError(
                            "ARTIFACT_QUARANTINE_DELETE_STATE_INVALID",
                            "completed deletion still has a quarantine capsule",
                        )
                    return result

                self._continue_delete(family.root, delete_intent)
                result = self._build_result(delete_intent)
                self.io.write_metadata(result_path, result)
                return result

    def _continue_delete(
        self,
        family_root: Path,
        intent: Mapping[str, Any],
    ) -> None:
        capsule = family_root / intent["capsule_name"]
        if not os.path.lexists(capsule):
            return
        self.io.require_directory(capsule)
        names = self._capsule_names(capsule)
        allowed = {
            "payload",
            "quarantine-intent.json",
            "quarantine-manifest.json",
        }
        if any(name not in allowed for name in names):
            raise ValidationError(
                "ARTIFACT_QUARANTINE_DELETE_CAPSULE_INVALID",
                "quarantine capsule contains unexpected entries",
            )

        remaining = [intent["plan_limits"]["scan_entries"] + 3]
        payload = capsule / "payload"
        if os.path.lexists(payload):
            self._remove_path(
                payload,
                depth=0,
                max_depth=intent["plan_limits"]["scan_depth"],
                remaining=remaining,
            )
            self.io.fsync_directory(capsule)

        for name in ("quarantine-intent.json", "quarantine-manifest.json"):
            path = capsule / name
            if not os.path.lexists(path):
                continue
            self._remove_regular_metadata(path, remaining)
        self.io.fsync_directory(capsule)
        try:
            capsule.rmdir()
        except OSError as exc:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_DELETE_CAPSULE_NOT_EMPTY",
                "cannot remove the emptied quarantine capsule",
            ) from exc
        self.io.fsync_directory(family_root)

    def _remove_path(
        self,
        path: Path,
        *,
        depth: int,
        max_depth: int,
        remaining: list[int],
    ) -> None:
        self._consume_budget(remaining)
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_DELETE_SCAN_FAILED",
                "cannot inspect quarantined content during deletion",
            ) from exc
        mode = metadata.st_mode
        if stat.S_ISDIR(mode) and not stat.S_ISLNK(mode):
            try:
                with os.scandir(path) as iterator:
                    children = sorted(
                        (Path(item.path) for item in iterator),
                        key=lambda item: item.name,
                    )
            except OSError as exc:
                raise ValidationError(
                    "ARTIFACT_QUARANTINE_DELETE_SCAN_FAILED",
                    "cannot enumerate quarantined content during deletion",
                ) from exc
            if children and depth >= max_depth:
                raise ValidationError(
                    "ARTIFACT_QUARANTINE_DELETE_DEPTH_EXCEEDED",
                    "quarantined content exceeds its recorded depth limit",
                )
            for child in children:
                self._remove_path(
                    child,
                    depth=depth + 1,
                    max_depth=max_depth,
                    remaining=remaining,
                )
            self.io.fsync_directory(path)
            try:
                path.rmdir()
            except OSError as exc:
                raise ValidationError(
                    "ARTIFACT_QUARANTINE_DELETE_REMOVE_FAILED",
                    "cannot remove a quarantined directory",
                ) from exc
            return
        try:
            path.unlink()
        except OSError as exc:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_DELETE_REMOVE_FAILED",
                "cannot remove a quarantined non-directory entry",
            ) from exc

    def _remove_regular_metadata(
        self,
        path: Path,
        remaining: list[int],
    ) -> None:
        self._consume_budget(remaining)
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_DELETE_METADATA_FAILED",
                "cannot inspect quarantine metadata during deletion",
            ) from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ValidationError(
                "ARTIFACT_QUARANTINE_DELETE_METADATA_FAILED",
                "quarantine metadata must remain regular non-symlink files",
            )
        try:
            path.unlink()
        except OSError as exc:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_DELETE_METADATA_FAILED",
                "cannot remove quarantine metadata",
            ) from exc

    @staticmethod
    def _consume_budget(remaining: list[int]) -> None:
        if remaining[0] <= 0:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_DELETE_SCAN_LIMIT_EXCEEDED",
                "permanent deletion exceeds the recorded bounded scan limit",
            )
        remaining[0] -= 1

    def _build_intent(
        self,
        quarantine_intent: Mapping[str, Any],
        verification: Mapping[str, Any],
        *,
        delete_id: str,
        deleted_at_unix_ns: int,
    ) -> dict[str, Any]:
        entry = quarantine_intent["plan_entry"]
        identity = {
            "format": ARTIFACT_QUARANTINE_DELETE_INTENT_FORMAT,
            "delete_id": delete_id,
            "quarantine_id": quarantine_intent["quarantine_id"],
            "quarantine_entry_id": quarantine_intent["quarantine_entry_id"],
            "quarantine_intent_id": quarantine_intent["intent_id"],
            "manifest_id": verification["manifest_id"],
            "plan_id": quarantine_intent["plan_id"],
            "verification_id": verification["verification_id"],
            "verification_reconciliation_id": verification["reconciliation_id"],
            "database_snapshot_id": verification["database_snapshot_id"],
            "family": quarantine_intent["family"],
            "capsule_name": quarantine_intent["final_name"],
            "source_lock_name": quarantine_intent["source_lock_name"],
            "original_entry_id": entry["entry_id"],
            "artifact_id": entry.get("artifact_id"),
            "original_classification": entry["classification"],
            "original_entry_type": entry["entry_type"],
            "minimum_holding_seconds": verification[
                "minimum_holding_seconds"
            ],
            "as_of_unix_ns": verification["as_of_unix_ns"],
            "deleted_at_unix_ns": deleted_at_unix_ns,
            "plan_limits": dict(quarantine_intent["plan_limits"]),
            "payload": dict(verification["payload"]),
        }
        return {**identity, "delete_intent_id": hash_json(identity)}

    def _validate_intent(
        self,
        value: Any,
        *,
        quarantine_intent: Mapping[str, Any],
        delete_id: str,
        manifest_id: str,
        plan_id: str,
        verification_id: str,
        minimum_holding_seconds: int,
        as_of_unix_ns: int,
    ) -> dict[str, Any]:
        if not isinstance(value, Mapping) or set(value) != _DELETE_INTENT_KEYS:
            self._metadata_error("delete intent has invalid or missing fields")
        intent = dict(value)
        identity = {
            name: item
            for name, item in intent.items()
            if name != "delete_intent_id"
        }
        if intent["delete_intent_id"] != hash_json(identity):
            self._metadata_error("delete intent identity is invalid")
        expected = {
            "delete_id": delete_id,
            "quarantine_id": quarantine_intent["quarantine_id"],
            "quarantine_entry_id": quarantine_intent["quarantine_entry_id"],
            "quarantine_intent_id": quarantine_intent["intent_id"],
            "manifest_id": manifest_id,
            "plan_id": plan_id,
            "verification_id": verification_id,
            "family": quarantine_intent["family"],
            "capsule_name": quarantine_intent["final_name"],
            "source_lock_name": quarantine_intent["source_lock_name"],
            "minimum_holding_seconds": minimum_holding_seconds,
            "as_of_unix_ns": as_of_unix_ns,
        }
        if (
            intent["format"] != ARTIFACT_QUARANTINE_DELETE_INTENT_FORMAT
            or any(intent.get(name) != item for name, item in expected.items())
        ):
            self._metadata_error("delete intent does not match the exact request")
        self._require_unix_ns(
            "deleted_at_unix_ns",
            intent["deleted_at_unix_ns"],
        )
        return intent

    def _build_result(self, intent: Mapping[str, Any]) -> dict[str, Any]:
        identity = {
            "format": ARTIFACT_QUARANTINE_DELETE_RESULT_FORMAT,
            "complete": True,
            "mutation": "delete",
            "deletion": "permanent",
            "restorable": False,
            "delete_id": intent["delete_id"],
            "delete_intent_id": intent["delete_intent_id"],
            "quarantine_id": intent["quarantine_id"],
            "quarantine_entry_id": intent["quarantine_entry_id"],
            "quarantine_intent_id": intent["quarantine_intent_id"],
            "manifest_id": intent["manifest_id"],
            "plan_id": intent["plan_id"],
            "verification_id": intent["verification_id"],
            "family": intent["family"],
            "original_entry_id": intent["original_entry_id"],
            "artifact_id": intent["artifact_id"],
            "original_classification": intent["original_classification"],
            "original_entry_type": intent["original_entry_type"],
            "deleted_at_unix_ns": intent["deleted_at_unix_ns"],
            "logical_bytes_reclaimed": intent["payload"]["logical_bytes"],
            "payload_entries_deleted": intent["payload"]["entries_scanned"],
        }
        return {**identity, "delete_result_id": hash_json(identity)}

    def _validate_result(
        self,
        value: Any,
        *,
        delete_intent: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(value, Mapping) or set(value) != _DELETE_RESULT_KEYS:
            self._metadata_error("delete result has invalid or missing fields")
        result = dict(value)
        identity = {
            name: item
            for name, item in result.items()
            if name != "delete_result_id"
        }
        if result["delete_result_id"] != hash_json(identity):
            self._metadata_error("delete result identity is invalid")
        if result != self._build_result(delete_intent):
            self._metadata_error("delete result does not match its exact intent")
        return result

    def _capsule_names(self, capsule: Path) -> list[str]:
        try:
            with os.scandir(capsule) as iterator:
                return sorted(item.name for item in iterator)
        except OSError as exc:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_DELETE_CAPSULE_UNAVAILABLE",
                "cannot enumerate the quarantine capsule",
            ) from exc

    @staticmethod
    def _require_sha256(name: str, value: Any) -> None:
        if not is_sha256(value):
            raise ValidationError(
                "ARTIFACT_QUARANTINE_DELETE_ID_INVALID",
                f"{name} must be 64 lowercase hexadecimal characters",
            )

    @staticmethod
    def _require_nonnegative_int(name: str, value: Any) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_DELETE_ARGUMENT_INVALID",
                f"{name} must be a non-negative integer",
            )

    @classmethod
    def _require_unix_ns(cls, name: str, value: Any) -> None:
        cls._require_nonnegative_int(name, value)
        if value > _MAX_UNIX_NS:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_DELETE_ARGUMENT_INVALID",
                f"{name} exceeds signed 64-bit time",
            )

    @staticmethod
    def _metadata_error(message: str) -> None:
        raise ValidationError(
            "ARTIFACT_QUARANTINE_DELETE_METADATA_INVALID",
            message,
        )


__all__ = [
    "ARTIFACT_QUARANTINE_DELETE_FORMAT",
    "ARTIFACT_QUARANTINE_DELETE_INTENT_FORMAT",
    "ARTIFACT_QUARANTINE_DELETE_RESULT_FORMAT",
    "ArtifactQuarantineDeleteService",
]
