"""Deterministic mutation-free retention planning."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .artifact_retention_accounting import (
    MAX_RETENTION_SCAN_DEPTH,
    MAX_RETENTION_SCAN_ENTRIES,
    ArtifactRetentionAccountant,
)
from .artifact_retention_catalog import ArtifactRetentionCatalog
from .artifact_retention_policy import (
    ARTIFACT_RETENTION_POLICY_FORMAT,
    MAX_RETENTION_PROTECTED_IDS,
    MAX_RETENTION_RULES,
    RETENTION_SELECTABLE_CLASSIFICATIONS,
    entry_order,
    hash_json,
    normalize_retention_policy,
    validate_positive,
    validate_unix_ns,
)
from .errors import ValidationError

ARTIFACT_RETENTION_PLAN_FORMAT = "weave-artifact-retention-plan-v1"
MAX_RETENTION_PLAN_ENTRIES = 10_000


class ArtifactRetentionPlanner:
    """Build a path-redacted dry-run plan from exact reconciliation evidence."""

    def __init__(
        self,
        reconciliation: Any,
        *,
        max_plan_entries: int = MAX_RETENTION_PLAN_ENTRIES,
        max_scan_entries: int = MAX_RETENTION_SCAN_ENTRIES,
        max_scan_depth: int = MAX_RETENTION_SCAN_DEPTH,
    ) -> None:
        if not hasattr(reconciliation, "inventory"):
            raise TypeError("reconciliation must expose its retained artifact inventory")
        validate_positive("max_plan_entries", max_plan_entries)
        self.reconciliation = reconciliation
        self.max_plan_entries = max_plan_entries
        self.catalog = ArtifactRetentionCatalog(reconciliation)
        self.accountant = ArtifactRetentionAccountant(
            reconciliation.inventory,
            max_scan_entries=max_scan_entries,
            max_scan_depth=max_scan_depth,
        )

    def plan(
        self,
        policy: Mapping[str, Any],
        *,
        as_of_unix_ns: int,
    ) -> dict[str, Any]:
        """Return one complete deterministic dry-run plan without mutation."""

        validate_unix_ns(as_of_unix_ns)
        normalized, rules = normalize_retention_policy(
            self.reconciliation,
            policy,
        )
        expected_id = normalized["reconciliation_id"]
        reconciliation_id, entries, locations = self.catalog.snapshot(expected_id)
        selected, rule_reports = self._select(entries, rules, as_of_unix_ns)
        if len(selected) > self.max_plan_entries:
            raise ValidationError(
                "ARTIFACT_RETENTION_PLAN_LIMIT_EXCEEDED",
                "retention plan exceeds the bounded selected-entry limit",
            )

        remaining = self.accountant.max_scan_entries
        planned = []
        for entry, rule in selected:
            measured, remaining = self.accountant.measure(entry["path"], remaining)
            item = {
                "family": entry["family"],
                "classification": entry["classification"],
                "entry_id": entry["entry_id"],
                "entry_type": entry["entry_type"],
                "mtime_unix_ns": entry["mtime_ns"],
                "age_seconds": max(
                    0,
                    (as_of_unix_ns - entry["mtime_ns"]) // 1_000_000_000,
                ),
                "rule_id": hash_json(rule),
                **measured,
            }
            if entry["artifact_id"] is not None:
                item["artifact_id"] = entry["artifact_id"]
            planned.append(item)
        planned.sort(key=entry_order)
        self.catalog.verify_unchanged(reconciliation_id, locations)

        policy_id = hash_json(normalized)
        limits = {
            "rules": MAX_RETENTION_RULES,
            "protected_artifact_ids": MAX_RETENTION_PROTECTED_IDS,
            "selected_entries": self.max_plan_entries,
            "scan_entries": self.accountant.max_scan_entries,
            "scan_depth": self.accountant.max_scan_depth,
        }
        aggregate = {
            "selected_entry_count": len(planned),
            "projected_logical_bytes": sum(item["logical_bytes"] for item in planned),
            "regular_files": sum(item["regular_files"] for item in planned),
            "directories": sum(item["directories"] for item in planned),
            "symlinks": sum(item["symlinks"] for item in planned),
            "special_entries": sum(item["special_entries"] for item in planned),
            "entries_scanned": sum(item["entries_scanned"] for item in planned),
        }
        identity = {
            "format": ARTIFACT_RETENTION_PLAN_FORMAT,
            "reconciliation_id": reconciliation_id,
            "policy_id": policy_id,
            "as_of_unix_ns": as_of_unix_ns,
            "rules": rule_reports,
            "entries": planned,
            "limits": limits,
        }
        return {
            "format": ARTIFACT_RETENTION_PLAN_FORMAT,
            "complete": True,
            "dry_run": True,
            "mutation": "none",
            "reconciliation_id": reconciliation_id,
            "policy_id": policy_id,
            "plan_id": hash_json(identity),
            "as_of_unix_ns": as_of_unix_ns,
            "aggregate": aggregate,
            "families": self._families(planned),
            "rules": rule_reports,
            "entries": planned,
            "limits": limits,
        }

    @staticmethod
    def _select(
        entries: tuple[dict[str, Any], ...],
        rules: tuple[dict[str, Any], ...],
        as_of_unix_ns: int,
    ) -> tuple[
        tuple[tuple[dict[str, Any], dict[str, Any]], ...],
        list[dict[str, Any]],
    ]:
        selected = []
        reports = []
        for rule in rules:
            matching = [
                item
                for item in entries
                if item["family"] == rule["family"]
                and item["classification"] == rule["classification"]
            ]
            matching.sort(
                key=lambda item: (
                    -item["mtime_ns"],
                    item["artifact_id"] or "",
                    item["entry_id"],
                )
            )
            retained = {item["entry_id"] for item in matching[: rule["minimum_retained_count"]]}
            protected = set(rule["protected_artifact_ids"])
            chosen = [
                item
                for item in matching
                if item["entry_id"] not in retained
                and item["artifact_id"] not in protected
                and as_of_unix_ns - item["mtime_ns"] >= rule["minimum_age_seconds"] * 1_000_000_000
            ]
            selected.extend((item, rule) for item in chosen)
            reports.append(
                {
                    **rule,
                    "rule_id": hash_json(rule),
                    "matching_entry_count": len(matching),
                    "selected_entry_count": len(chosen),
                }
            )
        return (
            tuple(sorted(selected, key=lambda pair: entry_order(pair[0]))),
            reports,
        )

    @staticmethod
    def _families(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "family": family,
                "selected_entry_count": sum(item["family"] == family for item in entries),
                "projected_logical_bytes": sum(
                    item["logical_bytes"] for item in entries if item["family"] == family
                ),
            }
            for family in sorted({item["family"] for item in entries})
        ]


__all__ = [
    "ARTIFACT_RETENTION_PLAN_FORMAT",
    "ARTIFACT_RETENTION_POLICY_FORMAT",
    "MAX_RETENTION_PLAN_ENTRIES",
    "MAX_RETENTION_PROTECTED_IDS",
    "MAX_RETENTION_RULES",
    "MAX_RETENTION_SCAN_DEPTH",
    "MAX_RETENTION_SCAN_ENTRIES",
    "RETENTION_SELECTABLE_CLASSIFICATIONS",
    "ArtifactRetentionPlanner",
]
