"""Contracts for exact, idempotent restore from artifact quarantine."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ...artifacts.retention import (
    RETENTION_SELECTABLE_CLASSIFICATIONS,
    hash_json,
    is_sha256,
)
from ...errors import ValidationError
from .contract import (
    ARTIFACT_QUARANTINE_ENTRY_FORMAT,
    ARTIFACT_QUARANTINE_INTENT_FORMAT,
    build_manifest,
    valid_capture,
    verify_relocation,
)

ARTIFACT_QUARANTINE_RESTORE_FORMAT = "weave-artifact-quarantine-restore-v1"
ARTIFACT_QUARANTINE_RESTORE_INTENT_FORMAT = "weave-artifact-quarantine-restore-intent-v1"
ARTIFACT_QUARANTINE_RESTORE_RESULT_FORMAT = "weave-artifact-quarantine-restore-result-v1"

_QUARANTINE_INTENT_KEYS = {
    "format",
    "quarantine_id",
    "quarantine_entry_id",
    "plan_id",
    "plan_document_id",
    "reconciliation_id",
    "policy_id",
    "family",
    "original_name",
    "source_lock_name",
    "source_lock_entry_id",
    "source_lock_was_present",
    "final_name",
    "staging_name",
    "quarantined_at_unix_ns",
    "plan_entry",
    "plan_limits",
    "database_snapshot_id",
    "inventory_id",
    "catalog_state_id",
    "original_identity_record",
    "original_location_record",
    "original_root_record",
    "source_capture",
    "intent_id",
}
_RESTORE_INTENT_KEYS = {
    "format",
    "restore_id",
    "quarantine_id",
    "quarantine_entry_id",
    "quarantine_intent_id",
    "manifest_id",
    "family",
    "capsule_name",
    "original_name",
    "source_lock_name",
    "original_entry_id",
    "artifact_id",
    "original_classification",
    "original_entry_type",
    "plan_id",
    "reconciliation_id",
    "restored_at_unix_ns",
    "plan_limits",
    "source_capture",
    "restore_intent_id",
}
_RESTORE_RESULT_KEYS = {
    "format",
    "complete",
    "mutation",
    "deletion",
    "restorable",
    "restore_id",
    "restore_result_id",
    "restore_intent_id",
    "quarantine_id",
    "quarantine_entry_id",
    "quarantine_intent_id",
    "manifest_id",
    "family",
    "original_entry_id",
    "artifact_id",
    "original_classification",
    "original_entry_type",
    "plan_id",
    "reconciliation_id",
    "restored_at_unix_ns",
    "payload",
}


def restore_identities(quarantine_id: Any, manifest_id: Any) -> str:
    """Validate exact operator identities and derive one restore identity."""

    _require_sha256("quarantine_id", quarantine_id)
    _require_sha256("manifest_id", manifest_id)
    return hash_json(
        {
            "format": ARTIFACT_QUARANTINE_RESTORE_FORMAT,
            "quarantine_id": quarantine_id,
            "manifest_id": manifest_id,
        }
    )


def validate_stored_quarantine_intent(
    value: Any,
    *,
    quarantine_id: str,
) -> dict[str, Any]:
    """Validate one durable v1 quarantine journal without the original plan."""

    if not isinstance(value, Mapping) or set(value) != _QUARANTINE_INTENT_KEYS:
        _metadata_error("quarantine journal has invalid or missing fields")
    intent = dict(value)
    identity = {key: item for key, item in intent.items() if key != "intent_id"}
    if (
        intent["format"] != ARTIFACT_QUARANTINE_INTENT_FORMAT
        or intent["quarantine_id"] != quarantine_id
        or intent["intent_id"] != hash_json(identity)
    ):
        _metadata_error("quarantine journal identity is invalid")
    for name in (
        "quarantine_id",
        "quarantine_entry_id",
        "intent_id",
        "plan_id",
        "plan_document_id",
        "reconciliation_id",
        "policy_id",
        "source_lock_entry_id",
        "database_snapshot_id",
        "inventory_id",
        "catalog_state_id",
    ):
        _require_sha256(name, intent.get(name), metadata=True)
    family = intent.get("family")
    if not isinstance(family, str) or not family:
        _metadata_error("quarantine family is invalid")
    _require_basename("original_name", intent.get("original_name"))
    if intent.get("source_lock_name") != f".{intent['original_name']}.lock":
        _metadata_error("quarantine source lock name is invalid")
    expected_final = f".quarantine-{intent['quarantine_entry_id']}"
    if (
        intent.get("final_name") != expected_final
        or intent.get("staging_name") != f"{expected_final}.staging"
    ):
        _metadata_error("quarantine capsule names are invalid")
    if not isinstance(intent.get("source_lock_was_present"), bool):
        _metadata_error("quarantine source lock state is invalid")
    _require_unix_ns(
        "quarantined_at_unix_ns",
        intent.get("quarantined_at_unix_ns"),
        metadata=True,
    )
    _validate_limits(intent.get("plan_limits"))

    entry = intent.get("plan_entry")
    original_identity = intent.get("original_identity_record")
    original_location = intent.get("original_location_record")
    original_root = intent.get("original_root_record")
    if not isinstance(entry, Mapping):
        _metadata_error("quarantine plan entry is invalid")
    if any(
        not isinstance(item, Mapping)
        for item in (original_identity, original_location, original_root)
    ):
        _metadata_error("quarantine original state records are invalid")
    if (
        entry.get("family") != family
        or entry.get("entry_id") != original_identity.get("entry_id")
        or entry.get("classification") not in RETENTION_SELECTABLE_CLASSIFICATIONS
        or entry.get("entry_type") not in {"directory", "regular_file", "symlink", "special"}
    ):
        _metadata_error("quarantine plan entry does not match stored state")
    _require_sha256("original_entry_id", entry.get("entry_id"), metadata=True)
    artifact_id = entry.get("artifact_id")
    if artifact_id is not None and not isinstance(artifact_id, str):
        _metadata_error("quarantine artifact identity is invalid")
    if not valid_capture(intent.get("source_capture")):
        _metadata_error("quarantine source capture is invalid")
    if (
        original_location.get("entry_id") != entry["entry_id"]
        or original_location.get("family") != family
        or original_root.get("family") != family
    ):
        _metadata_error("quarantine original state records do not match")
    return intent


def validate_stored_manifest(
    value: Any,
    *,
    intent: Mapping[str, Any],
    manifest_id: str,
) -> dict[str, Any]:
    """Validate one exact self-identifying quarantine manifest."""

    _require_sha256("manifest_id", manifest_id)
    if not isinstance(value, Mapping):
        _metadata_error("quarantine manifest must be an object")
    manifest = dict(value)
    identity = {key: item for key, item in manifest.items() if key != "manifest_id"}
    if manifest.get("manifest_id") != manifest_id or hash_json(identity) != manifest_id:
        _metadata_error("quarantine manifest identity is invalid")
    entry = intent["plan_entry"]
    expected = {
        "format": ARTIFACT_QUARANTINE_ENTRY_FORMAT,
        "quarantine_id": intent["quarantine_id"],
        "quarantine_entry_id": intent["quarantine_entry_id"],
        "intent_id": intent["intent_id"],
        "plan_id": intent["plan_id"],
        "plan_document_id": intent["plan_document_id"],
        "reconciliation_id": intent["reconciliation_id"],
        "policy_id": intent["policy_id"],
        "family": intent["family"],
        "original_name": intent["original_name"],
        "original_entry_id": entry["entry_id"],
        "artifact_id": entry.get("artifact_id"),
        "original_classification": entry["classification"],
        "original_entry_type": entry["entry_type"],
        "payload": "payload",
        "quarantined_at_unix_ns": intent["quarantined_at_unix_ns"],
        "source_entry_snapshot_id": intent["source_capture"]["entry_snapshot_id"],
        "source_relocation_snapshot_id": intent["source_capture"]["relocation_snapshot_id"],
    }
    if any(manifest.get(name) != item for name, item in expected.items()):
        _metadata_error("quarantine manifest does not match its journal")
    return manifest


def build_restore_intent(
    quarantine_intent: Mapping[str, Any],
    *,
    manifest_id: str,
    restore_id: str,
    restored_at_unix_ns: int,
) -> dict[str, Any]:
    """Build immutable restore intent before the payload move."""

    _require_unix_ns("restored_at_unix_ns", restored_at_unix_ns)
    entry = quarantine_intent["plan_entry"]
    identity = {
        "format": ARTIFACT_QUARANTINE_RESTORE_INTENT_FORMAT,
        "restore_id": restore_id,
        "quarantine_id": quarantine_intent["quarantine_id"],
        "quarantine_entry_id": quarantine_intent["quarantine_entry_id"],
        "quarantine_intent_id": quarantine_intent["intent_id"],
        "manifest_id": manifest_id,
        "family": quarantine_intent["family"],
        "capsule_name": quarantine_intent["final_name"],
        "original_name": quarantine_intent["original_name"],
        "source_lock_name": quarantine_intent["source_lock_name"],
        "original_entry_id": entry["entry_id"],
        "artifact_id": entry.get("artifact_id"),
        "original_classification": entry["classification"],
        "original_entry_type": entry["entry_type"],
        "plan_id": quarantine_intent["plan_id"],
        "reconciliation_id": quarantine_intent["reconciliation_id"],
        "restored_at_unix_ns": restored_at_unix_ns,
        "plan_limits": dict(quarantine_intent["plan_limits"]),
        "source_capture": dict(quarantine_intent["source_capture"]),
    }
    return {**identity, "restore_intent_id": hash_json(identity)}


def validate_restore_intent(
    value: Any,
    *,
    quarantine_intent: Mapping[str, Any],
    manifest_id: str,
    restore_id: str,
) -> dict[str, Any]:
    """Validate an immutable restore journal against exact quarantine evidence."""

    if not isinstance(value, Mapping) or set(value) != _RESTORE_INTENT_KEYS:
        _restore_error("restore intent has invalid or missing fields")
    intent = dict(value)
    identity = {key: item for key, item in intent.items() if key != "restore_intent_id"}
    if intent["restore_intent_id"] != hash_json(identity):
        _restore_error("restore intent identity is invalid")
    expected = build_restore_intent(
        quarantine_intent,
        manifest_id=manifest_id,
        restore_id=restore_id,
        restored_at_unix_ns=intent["restored_at_unix_ns"],
    )
    if intent != expected:
        _restore_error("restore intent does not match exact quarantine evidence")
    return intent


def build_restore_result(
    restore_intent: Mapping[str, Any],
    capture: Mapping[str, Any],
) -> dict[str, Any]:
    """Build path-redacted durable evidence for one completed restore."""

    if not valid_capture(capture):
        _restore_error("restored payload capture is invalid")
    identity = {
        "format": ARTIFACT_QUARANTINE_RESTORE_RESULT_FORMAT,
        "complete": True,
        "mutation": "restore",
        "deletion": "quarantine-metadata-only",
        "restorable": False,
        "restore_id": restore_intent["restore_id"],
        "restore_intent_id": restore_intent["restore_intent_id"],
        "quarantine_id": restore_intent["quarantine_id"],
        "quarantine_entry_id": restore_intent["quarantine_entry_id"],
        "quarantine_intent_id": restore_intent["quarantine_intent_id"],
        "manifest_id": restore_intent["manifest_id"],
        "family": restore_intent["family"],
        "original_entry_id": restore_intent["original_entry_id"],
        "artifact_id": restore_intent["artifact_id"],
        "original_classification": restore_intent["original_classification"],
        "original_entry_type": restore_intent["original_entry_type"],
        "plan_id": restore_intent["plan_id"],
        "reconciliation_id": restore_intent["reconciliation_id"],
        "restored_at_unix_ns": restore_intent["restored_at_unix_ns"],
        "payload": dict(capture),
    }
    return {**identity, "restore_result_id": hash_json(identity)}


def validate_restore_result(
    value: Any,
    *,
    restore_intent: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate durable completion evidence for idempotent retries."""

    if not isinstance(value, Mapping) or set(value) != _RESTORE_RESULT_KEYS:
        _restore_error("restore result has invalid or missing fields")
    result = dict(value)
    identity = {key: item for key, item in result.items() if key != "restore_result_id"}
    if result["restore_result_id"] != hash_json(identity):
        _restore_error("restore result identity is invalid")
    expected = build_restore_result(restore_intent, result["payload"])
    if result != expected:
        _restore_error("restore result does not match its exact intent")
    return result


def verify_payload_against_manifest(
    quarantine_intent: Mapping[str, Any],
    manifest: Mapping[str, Any],
    capture: Mapping[str, Any],
) -> None:
    """Verify the live quarantined payload before restoration."""

    expected = build_manifest(quarantine_intent, capture)
    if dict(manifest) != expected:
        _metadata_error("quarantined payload does not match its manifest")
    verify_relocation(quarantine_intent["source_capture"], capture)


def verify_restored_payload(
    restore_intent: Mapping[str, Any],
    capture: Mapping[str, Any],
) -> None:
    """Verify a restored payload against the original relocation identity."""

    verify_relocation(restore_intent["source_capture"], capture)


def verify_result_payload(
    result: Mapping[str, Any],
    capture: Mapping[str, Any],
) -> None:
    """Require idempotent replay to match the durable completion snapshot."""

    if not valid_capture(capture) or dict(result["payload"]) != dict(capture):
        _restore_error("live restored payload differs from completion evidence")


def _validate_limits(value: Any) -> None:
    if not isinstance(value, Mapping):
        _metadata_error("quarantine plan limits are invalid")
    scan_entries = value.get("scan_entries")
    scan_depth = value.get("scan_depth")
    if (
        isinstance(scan_entries, bool)
        or not isinstance(scan_entries, int)
        or scan_entries <= 0
        or isinstance(scan_depth, bool)
        or not isinstance(scan_depth, int)
        or scan_depth < 0
    ):
        _metadata_error("quarantine scan limits are invalid")


def _require_basename(name: str, value: Any) -> None:
    if not isinstance(value, str) or not value or value in {".", ".."} or Path(value).name != value:
        _metadata_error(f"{name} must be one safe path component")


def _require_sha256(
    name: str,
    value: Any,
    *,
    metadata: bool = False,
) -> None:
    if not is_sha256(value):
        if metadata:
            _metadata_error(f"{name} must be lowercase SHA-256")
        raise ValidationError(
            "ARTIFACT_QUARANTINE_RESTORE_ID_INVALID",
            f"{name} must be 64 lowercase hexadecimal characters",
        )


def _require_unix_ns(
    name: str,
    value: Any,
    *,
    metadata: bool = False,
) -> None:
    invalid = isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 2**63 - 1
    if invalid:
        if metadata:
            _metadata_error(f"{name} must be a non-negative signed 64-bit integer")
        raise ValidationError(
            "ARTIFACT_QUARANTINE_RESTORE_TIMESTAMP_INVALID",
            f"{name} must be a non-negative signed 64-bit integer",
        )


def _metadata_error(message: str) -> None:
    raise ValidationError("ARTIFACT_QUARANTINE_RESTORE_METADATA_INVALID", message)


def _restore_error(message: str) -> None:
    raise ValidationError("ARTIFACT_QUARANTINE_RESTORE_STATE_INVALID", message)


__all__ = [
    "ARTIFACT_QUARANTINE_RESTORE_FORMAT",
    "ARTIFACT_QUARANTINE_RESTORE_INTENT_FORMAT",
    "ARTIFACT_QUARANTINE_RESTORE_RESULT_FORMAT",
    "build_restore_intent",
    "build_restore_result",
    "restore_identities",
    "validate_restore_intent",
    "validate_restore_result",
    "validate_stored_manifest",
    "validate_stored_quarantine_intent",
    "verify_payload_against_manifest",
    "verify_restored_payload",
    "verify_result_payload",
]
