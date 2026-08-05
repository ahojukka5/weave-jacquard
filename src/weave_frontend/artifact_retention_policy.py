"""Validation and canonical identity for explicit retention policies."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .artifact_reconciliation import RETAINED_ARTIFACT_FAMILIES
from .errors import ValidationError

ARTIFACT_RETENTION_POLICY_FORMAT = "weave-artifact-retention-policy-v1"
MAX_RETENTION_RULES = 64
MAX_RETENTION_PROTECTED_IDS = 10_000
RETENTION_SELECTABLE_CLASSIFICATIONS = (
    "corrupt",
    "orphaned",
    "staging",
    "unknown",
)


def normalize_retention_policy(
    reconciliation: Any,
    value: Mapping[str, Any],
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    """Validate and deterministically order one operator retention policy."""

    if not isinstance(value, Mapping) or set(value) != {
        "format",
        "reconciliation_id",
        "rules",
    }:
        _policy_error("policy must contain exactly format, reconciliation_id, and rules")
    if value["format"] != ARTIFACT_RETENTION_POLICY_FORMAT:
        _policy_error("policy format is unsupported")
    if not is_sha256(value["reconciliation_id"]):
        _policy_error("reconciliation_id must be 64 lowercase hex characters")
    raw_rules = value["rules"]
    if not isinstance(raw_rules, list) or not 1 <= len(raw_rules) <= MAX_RETENTION_RULES:
        _policy_error(f"rules must contain 1-{MAX_RETENTION_RULES} entries")

    patterns = {
        family.name: family.artifact_id_pattern for family in reconciliation.inventory.families
    }
    allowed = {
        "family",
        "classification",
        "minimum_age_seconds",
        "minimum_retained_count",
        "protected_artifact_ids",
    }
    required = allowed - {"protected_artifact_ids"}
    rules: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in raw_rules:
        if (
            not isinstance(raw, Mapping)
            or not required.issubset(raw)
            or not set(raw).issubset(allowed)
        ):
            _policy_error("rules have invalid or missing fields")
        family = raw["family"]
        classification = raw["classification"]
        if family not in RETAINED_ARTIFACT_FAMILIES or family not in patterns:
            _policy_error("rule family is not configured")
        if classification not in RETENTION_SELECTABLE_CLASSIFICATIONS:
            raise ValidationError(
                "ARTIFACT_RETENTION_UNSAFE_CLASSIFICATION",
                "planning may select only orphaned, corrupt, staging, or unknown entries",
            )
        pair = (family, classification)
        if pair in seen:
            _policy_error("duplicate family/classification rule")
        seen.add(pair)
        age = raw["minimum_age_seconds"]
        count = raw["minimum_retained_count"]
        validate_nonnegative("minimum_age_seconds", age, policy=True)
        validate_nonnegative("minimum_retained_count", count, policy=True)
        protected = raw.get("protected_artifact_ids", [])
        if (
            not isinstance(protected, list)
            or len(protected) > MAX_RETENTION_PROTECTED_IDS
            or any(not isinstance(item, str) for item in protected)
            or len(set(protected)) != len(protected)
        ):
            _policy_error("protected_artifact_ids must be a bounded unique string list")
        if any(patterns[family].fullmatch(item) is None for item in protected):
            _policy_error("protected artifact ID does not match its family contract")
        rules.append(
            {
                "family": family,
                "classification": classification,
                "minimum_age_seconds": age,
                "minimum_retained_count": count,
                "protected_artifact_ids": sorted(protected),
            }
        )
    ordered = tuple(sorted(rules, key=lambda item: (item["family"], item["classification"])))
    return (
        {
            "format": ARTIFACT_RETENTION_POLICY_FORMAT,
            "reconciliation_id": value["reconciliation_id"],
            "rules": list(ordered),
        },
        ordered,
    )


def entry_order(item: Mapping[str, Any]) -> tuple[Any, ...]:
    """Return the canonical ordering key for catalog and plan entries."""

    return (
        item["family"],
        item["classification"],
        item.get("mtime_unix_ns", item.get("mtime_ns", 0)),
        item.get("artifact_id") or "",
        item["entry_id"],
    )


def hash_json(value: Any) -> str:
    """Hash canonical JSON without timestamps or random values."""

    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def validate_unix_ns(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 2**63 - 1:
        _policy_error("as_of_unix_ns must be a non-negative signed 64-bit integer")


def validate_positive(name: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def validate_nonnegative(name: str, value: Any, *, policy: bool = False) -> None:
    invalid = isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 2**63 - 1
    if invalid and policy:
        _policy_error(f"{name} must be a non-negative signed 64-bit integer")
    if invalid:
        raise ValueError(f"{name} must be a non-negative signed 64-bit integer")


def _policy_error(message: str) -> None:
    raise ValidationError("ARTIFACT_RETENTION_POLICY_INVALID", message)


__all__ = [
    "ARTIFACT_RETENTION_POLICY_FORMAT",
    "MAX_RETENTION_PROTECTED_IDS",
    "MAX_RETENTION_RULES",
    "RETENTION_SELECTABLE_CLASSIFICATIONS",
    "entry_order",
    "hash_json",
    "is_sha256",
    "normalize_retention_policy",
    "validate_nonnegative",
    "validate_positive",
    "validate_unix_ns",
]
