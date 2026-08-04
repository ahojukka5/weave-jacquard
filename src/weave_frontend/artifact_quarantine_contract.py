"""Contracts and canonical identities for guarded artifact quarantine."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .artifact_retention import (
    ARTIFACT_RETENTION_PLAN_FORMAT,
    MAX_RETENTION_PLAN_ENTRIES,
)
from .artifact_retention_accounting import (
    MAX_RETENTION_SCAN_DEPTH,
    MAX_RETENTION_SCAN_ENTRIES,
)
from .artifact_retention_policy import (
    MAX_RETENTION_PROTECTED_IDS,
    MAX_RETENTION_RULES,
    RETENTION_SELECTABLE_CLASSIFICATIONS,
    hash_json,
    is_sha256,
    normalize_retention_policy,
)
from .errors import ValidationError

ARTIFACT_QUARANTINE_FORMAT = "weave-artifact-quarantine-v1"
ARTIFACT_QUARANTINE_INTENT_FORMAT = "weave-artifact-quarantine-intent-v1"
ARTIFACT_QUARANTINE_ENTRY_FORMAT = "weave-artifact-quarantine-entry-v1"

_PLAN_KEYS = {
    "format",
    "complete",
    "dry_run",
    "mutation",
    "reconciliation_id",
    "policy_id",
    "plan_id",
    "as_of_unix_ns",
    "aggregate",
    "families",
    "rules",
    "entries",
    "limits",
}
_PLAN_LIMIT_KEYS = {
    "rules",
    "protected_artifact_ids",
    "selected_entries",
    "scan_entries",
    "scan_depth",
}
_PLAN_LIMIT_MAXIMUMS = {
    "rules": MAX_RETENTION_RULES,
    "protected_artifact_ids": MAX_RETENTION_PROTECTED_IDS,
    "selected_entries": MAX_RETENTION_PLAN_ENTRIES,
    "scan_entries": MAX_RETENTION_SCAN_ENTRIES,
    "scan_depth": MAX_RETENTION_SCAN_DEPTH,
}
_PLAN_ENTRY_REQUIRED = {
    "family",
    "classification",
    "entry_id",
    "entry_type",
    "mtime_unix_ns",
    "age_seconds",
    "rule_id",
    "logical_bytes",
    "regular_files",
    "directories",
    "symlinks",
    "special_entries",
    "entries_scanned",
    "entry_snapshot_id",
}
_CAPTURE_COUNT_KEYS = (
    "logical_bytes",
    "regular_files",
    "directories",
    "symlinks",
    "special_entries",
    "entries_scanned",
)
_INTENT_KEYS = {
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


def validate_quarantine_request(
    reconciliation: Any,
    policy: Mapping[str, Any],
    plan: Mapping[str, Any],
    *,
    entry_id: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Validate one policy, self-identifying plan, and selected entry."""

    normalized_policy, _rules = normalize_retention_policy(
        reconciliation,
        policy,
    )
    if not isinstance(plan, Mapping) or set(plan) != _PLAN_KEYS:
        _plan_error("plan has invalid or missing fields")
    normalized_plan = copy.deepcopy(dict(plan))
    if (
        normalized_plan["format"] != ARTIFACT_RETENTION_PLAN_FORMAT
        or normalized_plan["complete"] is not True
        or normalized_plan["dry_run"] is not True
        or normalized_plan["mutation"] != "none"
    ):
        _plan_error("plan is not a complete dry-run retention plan")
    for name in ("reconciliation_id", "policy_id", "plan_id"):
        if not is_sha256(normalized_plan.get(name)):
            _plan_error(f"{name} must be lowercase SHA-256")
    if normalized_plan["reconciliation_id"] != normalized_policy[
        "reconciliation_id"
    ]:
        _plan_error("policy and plan reconciliation identities differ")
    if normalized_plan["policy_id"] != hash_json(normalized_policy):
        _plan_error("policy identity does not match the plan")
    _nonnegative_int("as_of_unix_ns", normalized_plan["as_of_unix_ns"])

    limits = normalized_plan["limits"]
    if not isinstance(limits, Mapping) or set(limits) != _PLAN_LIMIT_KEYS:
        _plan_error("plan limits are invalid")
    for name in _PLAN_LIMIT_KEYS:
        minimum = 0 if name == "scan_depth" else 1
        value = limits[name]
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not minimum <= value <= _PLAN_LIMIT_MAXIMUMS[name]
        ):
            _plan_error("plan limits are outside guarded quarantine bounds")

    entries = normalized_plan["entries"]
    rules = normalized_plan["rules"]
    if (
        not isinstance(entries, list)
        or len(entries) > limits["selected_entries"]
        or not isinstance(rules, list)
        or len(rules) > limits["rules"]
    ):
        _plan_error("plan entries or rules exceed their bounded limits")
    for item in entries:
        if not isinstance(item, Mapping):
            _plan_error("plan entries must be objects")
        _validate_plan_entry(reconciliation, item)
    if not isinstance(normalized_plan["aggregate"], Mapping):
        _plan_error("plan aggregate must be an object")
    if not isinstance(normalized_plan["families"], list):
        _plan_error("plan families must be a list")

    try:
        identity = {
            "format": ARTIFACT_RETENTION_PLAN_FORMAT,
            "reconciliation_id": normalized_plan["reconciliation_id"],
            "policy_id": normalized_plan["policy_id"],
            "as_of_unix_ns": normalized_plan["as_of_unix_ns"],
            "rules": rules,
            "entries": entries,
            "limits": dict(limits),
        }
        calculated_plan_id = hash_json(identity)
        hash_json(normalized_plan)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            "ARTIFACT_QUARANTINE_PLAN_INVALID",
            "plan is not canonical JSON",
        ) from exc
    if normalized_plan["plan_id"] != calculated_plan_id:
        _plan_error("plan identity is invalid")

    if not is_sha256(entry_id):
        raise ValidationError(
            "ARTIFACT_QUARANTINE_ENTRY_ID_INVALID",
            "entry_id must be 64 lowercase hexadecimal characters",
        )
    selected = next(
        (
            copy.deepcopy(dict(item))
            for item in entries
            if item.get("entry_id") == entry_id
        ),
        None,
    )
    if selected is None:
        raise ValidationError(
            "ARTIFACT_QUARANTINE_ENTRY_NOT_SELECTED",
            "entry_id is not selected by the exact retention plan",
        )
    return normalized_policy, normalized_plan, selected


def quarantine_identities(
    plan: Mapping[str, Any],
    entry: Mapping[str, Any],
) -> tuple[str, str]:
    """Return deterministic entry and operation quarantine identities."""

    quarantine_entry_id = hash_json(
        {
            "format": ARTIFACT_QUARANTINE_ENTRY_FORMAT,
            "plan_id": plan["plan_id"],
            "entry": entry,
        }
    )
    quarantine_id = hash_json(
        {
            "format": ARTIFACT_QUARANTINE_FORMAT,
            "plan_id": plan["plan_id"],
            "quarantine_entry_id": quarantine_entry_id,
        }
    )
    return quarantine_id, quarantine_entry_id


def build_intent(identity: Mapping[str, Any]) -> dict[str, Any]:
    """Add a canonical intent identity to validated private evidence."""

    payload = dict(identity)
    return {**payload, "intent_id": hash_json(payload)}


def validate_intent(
    intent: Mapping[str, Any],
    *,
    policy: Mapping[str, Any],
    plan: Mapping[str, Any],
    entry: Mapping[str, Any],
    quarantine_id: str,
    quarantine_entry_id: str,
    final_name: str,
    staging_name: str,
) -> None:
    """Validate durable intent against the exact operator request."""

    if not isinstance(intent, Mapping) or set(intent) != _INTENT_KEYS:
        _metadata_error("quarantine intent has invalid or missing fields")
    identity = {key: value for key, value in intent.items() if key != "intent_id"}
    if intent.get("intent_id") != hash_json(identity):
        _metadata_error("quarantine intent identity is invalid")
    expected = {
        "format": ARTIFACT_QUARANTINE_INTENT_FORMAT,
        "quarantine_id": quarantine_id,
        "quarantine_entry_id": quarantine_entry_id,
        "plan_id": plan["plan_id"],
        "plan_document_id": hash_json(plan),
        "reconciliation_id": plan["reconciliation_id"],
        "policy_id": hash_json(policy),
        "family": entry["family"],
        "final_name": final_name,
        "staging_name": staging_name,
        "plan_entry": dict(entry),
        "plan_limits": dict(plan["limits"]),
    }
    if any(intent.get(name) != value for name, value in expected.items()):
        _metadata_error("quarantine intent does not match the requested plan")
    validate_original_name(intent.get("original_name"))
    if intent.get("source_lock_name") != f".{intent['original_name']}.lock":
        _metadata_error("quarantine source lock identity is invalid")
    for name in (
        "database_snapshot_id",
        "inventory_id",
        "catalog_state_id",
        "source_lock_entry_id",
    ):
        if not is_sha256(intent.get(name)):
            _metadata_error("quarantine intent contains an invalid identity")
    if not isinstance(intent.get("source_lock_was_present"), bool):
        _metadata_error("quarantine source lock state is invalid")
    _nonnegative_int(
        "quarantined_at_unix_ns",
        intent.get("quarantined_at_unix_ns"),
        metadata=True,
    )
    _validate_private_records(intent, entry)
    capture = intent.get("source_capture")
    if not valid_capture(capture):
        _metadata_error("quarantine source snapshot is invalid")
    if capture["entry_snapshot_id"] != entry["entry_snapshot_id"]:
        _metadata_error("quarantine source snapshot differs from the plan")


def build_manifest(
    intent: Mapping[str, Any],
    capture: Mapping[str, Any],
) -> dict[str, Any]:
    """Build canonical verified metadata for one quarantined payload."""

    entry = intent["plan_entry"]
    identity = {
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
        "source_entry_snapshot_id": intent["source_capture"][
            "entry_snapshot_id"
        ],
        "source_relocation_snapshot_id": intent["source_capture"][
            "relocation_snapshot_id"
        ],
        "quarantined_entry_snapshot_id": capture["entry_snapshot_id"],
        "quarantined_relocation_snapshot_id": capture[
            "relocation_snapshot_id"
        ],
        **{name: capture[name] for name in _CAPTURE_COUNT_KEYS},
    }
    return {**identity, "manifest_id": hash_json(identity)}


def verify_relocation(
    source: Mapping[str, Any],
    quarantined: Mapping[str, Any],
) -> None:
    """Reject a payload that differs across the atomic rename."""

    changed = (
        source["relocation_snapshot_id"]
        != quarantined["relocation_snapshot_id"]
        or any(
            source[name] != quarantined[name]
            for name in _CAPTURE_COUNT_KEYS
        )
    )
    if changed:
        raise ValidationError(
            "ARTIFACT_QUARANTINE_RELOCATION_CHANGED",
            "quarantined payload differs from the locked source snapshot",
        )


def valid_capture(value: Any) -> bool:
    required = set(_CAPTURE_COUNT_KEYS) | {
        "entry_snapshot_id",
        "relocation_snapshot_id",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        return False
    if not is_sha256(value["entry_snapshot_id"]) or not is_sha256(
        value["relocation_snapshot_id"]
    ):
        return False
    return all(
        not isinstance(value[name], bool)
        and isinstance(value[name], int)
        and value[name] >= 0
        for name in _CAPTURE_COUNT_KEYS
    )


def validate_original_name(value: Any) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or Path(value).name != value
    ):
        _metadata_error("quarantine original name is invalid")


def _validate_private_records(
    intent: Mapping[str, Any],
    entry: Mapping[str, Any],
) -> None:
    identity = intent.get("original_identity_record")
    location = intent.get("original_location_record")
    root = intent.get("original_root_record")
    if (
        not isinstance(identity, Mapping)
        or identity.get("entry_id") != entry["entry_id"]
        or not isinstance(location, Mapping)
        or location.get("entry_id") != entry["entry_id"]
        or location.get("family") != entry["family"]
        or not isinstance(root, Mapping)
        or root.get("family") != entry["family"]
        or not is_sha256(root.get("root_id"))
    ):
        _metadata_error("quarantine original state records are invalid")
    stat_fields = {"mode", "device", "inode", "size", "mtime_ns", "ctime_ns"}
    if not stat_fields.issubset(location) or not stat_fields.issubset(root):
        _metadata_error("quarantine original stat records are incomplete")
    for record in (location, root):
        for name in stat_fields:
            _nonnegative_int(name, record.get(name), metadata=True)


def _validate_plan_entry(reconciliation: Any, entry: Mapping[str, Any]) -> None:
    keys = set(entry)
    if not _PLAN_ENTRY_REQUIRED.issubset(keys) or not keys.issubset(
        _PLAN_ENTRY_REQUIRED | {"artifact_id"}
    ):
        _plan_error("selected plan entry fields are invalid")
    patterns = {
        family.name: family.artifact_id_pattern
        for family in reconciliation.inventory.families
    }
    if entry["family"] not in patterns:
        _plan_error("selected plan entry family is not configured")
    if entry["classification"] not in RETENTION_SELECTABLE_CLASSIFICATIONS:
        _plan_error("selected plan entry classification is unsafe")
    if entry["entry_type"] not in {
        "directory",
        "regular_file",
        "symlink",
        "special",
    }:
        _plan_error("selected plan entry type is invalid")
    for name in ("entry_id", "entry_snapshot_id", "rule_id"):
        if not is_sha256(entry.get(name)):
            _plan_error("selected plan entry identities are invalid")
    artifact_id = entry.get("artifact_id")
    if (
        artifact_id is not None
        and patterns[entry["family"]].fullmatch(artifact_id) is None
    ):
        _plan_error("selected artifact identity is invalid for its family")
    for name in (
        "mtime_unix_ns",
        "age_seconds",
        *_CAPTURE_COUNT_KEYS,
    ):
        _nonnegative_int(name, entry.get(name))


def _nonnegative_int(
    name: str,
    value: Any,
    *,
    metadata: bool = False,
) -> None:
    invalid = (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= 2**63 - 1
    )
    if invalid:
        if metadata:
            _metadata_error(f"{name} must be a non-negative signed 64-bit integer")
        _plan_error(f"{name} must be a non-negative signed 64-bit integer")


def _plan_error(message: str) -> None:
    raise ValidationError("ARTIFACT_QUARANTINE_PLAN_INVALID", message)


def _metadata_error(message: str) -> None:
    raise ValidationError("ARTIFACT_QUARANTINE_METADATA_INVALID", message)


__all__ = [
    "ARTIFACT_QUARANTINE_ENTRY_FORMAT",
    "ARTIFACT_QUARANTINE_FORMAT",
    "ARTIFACT_QUARANTINE_INTENT_FORMAT",
    "build_intent",
    "build_manifest",
    "quarantine_identities",
    "valid_capture",
    "validate_intent",
    "validate_original_name",
    "validate_quarantine_request",
    "verify_relocation",
]
