"""Deterministic database-to-artifact reachability reconciliation."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifact_reconciliation import (
    MAX_RECONCILIATION_FAMILIES,
    RETAINED_ARTIFACT_INVENTORY_FORMAT,
    RetainedArtifactFamily,
    RetainedArtifactInventoryService,
)
from .database_integrity import (
    DATABASE_SEMANTIC_INTEGRITY_CONTRACT,
    inspect_connection,
)
from .errors import ArtifactIntegrityError, NotFoundError, ValidationError

ARTIFACT_RECONCILIATION_FORMAT = "weave-artifact-reconciliation-v1"
ARTIFACT_RECONCILIATION_DATABASE_FORMAT = (
    "weave-artifact-reconciliation-database-v1"
)
MAX_RECONCILIATION_DATABASE_PROJECTS = 100_000
MAX_RECONCILIATION_DATABASE_REVISIONS = 1_000_000
MAX_RECONCILIATION_RELATIONSHIPS = 2_000_000

_INVENTORY_CLASSIFICATIONS = (
    "verified",
    "corrupt",
    "staging",
    "quarantined",
    "lock_internal",
    "unknown",
)
_RECONCILIATION_CLASSIFICATIONS = (
    "reachable",
    "orphaned",
    "missing",
    "corrupt",
    "staging",
    "quarantined",
    "lock_internal",
    "unknown",
)


@dataclass(frozen=True)
class _DatabaseSnapshot:
    report: dict[str, Any]
    revision_projects: dict[str, str]


@dataclass(frozen=True)
class _InventorySnapshot:
    report: dict[str, Any]
    records: tuple[dict[str, Any], ...]
    evidence: dict[tuple[str, str], dict[str, Any]]


class ArtifactReconciliationService:
    """Connect one immutable database snapshot to all retained artifact stores."""

    def __init__(
        self,
        database: Any,
        inventory: RetainedArtifactInventoryService,
        *,
        max_database_projects: int = MAX_RECONCILIATION_DATABASE_PROJECTS,
        max_database_revisions: int = MAX_RECONCILIATION_DATABASE_REVISIONS,
        max_relationships: int = MAX_RECONCILIATION_RELATIONSHIPS,
        max_examples: int | None = None,
    ) -> None:
        if not hasattr(database, "path"):
            raise TypeError("database must expose a filesystem path")
        if not isinstance(inventory, RetainedArtifactInventoryService):
            raise TypeError("inventory must be a RetainedArtifactInventoryService")
        self._validate_positive_limit(
            "max_database_projects",
            max_database_projects,
        )
        self._validate_positive_limit(
            "max_database_revisions",
            max_database_revisions,
        )
        self._validate_positive_limit("max_relationships", max_relationships)
        effective_examples = (
            inventory.max_examples
            if max_examples is None
            else max_examples
        )
        self._validate_positive_limit("max_examples", effective_examples)

        self.database = database
        self.inventory = inventory
        self.max_database_projects = max_database_projects
        self.max_database_revisions = max_database_revisions
        self.max_relationships = max_relationships
        self.max_examples = effective_examples

    def report(self) -> dict[str, Any]:
        """Return complete deterministic path-redacted reconciliation evidence."""

        database_before = self._database_snapshot()
        inventory = self._inventory_snapshot()
        database_after = self._database_snapshot()
        if (
            database_before.report["database_snapshot_id"]
            != database_after.report["database_snapshot_id"]
        ):
            raise ValidationError(
                "ARTIFACT_RECONCILIATION_DATABASE_CHANGED",
                "database reachability changed during artifact reconciliation",
            )

        report = self._reconcile(database_before, inventory)
        identity = {
            "format": ARTIFACT_RECONCILIATION_FORMAT,
            "database_snapshot_id": database_before.report[
                "database_snapshot_id"
            ],
            "inventory_id": inventory.report["inventory_id"],
            "families": report.pop("_identity_families"),
        }
        return {
            **report,
            "reconciliation_id": self._hash_json(identity),
        }

    def _database_snapshot(self) -> _DatabaseSnapshot:
        path = Path(self.database.path).expanduser().resolve()
        if not path.is_file():
            raise ValidationError(
                "ARTIFACT_RECONCILIATION_DATABASE_UNAVAILABLE",
                "reconciliation database file is unavailable",
            )
        uri = path.as_uri() + "?mode=ro"
        try:
            connection = sqlite3.connect(uri, uri=True)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            connection.execute("BEGIN")
            integrity = inspect_connection(connection)
            if integrity.get("valid") is not True:
                raise ValidationError(
                    "ARTIFACT_RECONCILIATION_DATABASE_INVALID",
                    "database must pass semantic integrity before reconciliation",
                )
            projects = list(
                connection.execute(
                    """SELECT id, name
                       FROM projects
                       ORDER BY name, id
                       LIMIT ?""",
                    (self.max_database_projects + 1,),
                )
            )
            if len(projects) > self.max_database_projects:
                raise ValidationError(
                    "ARTIFACT_RECONCILIATION_DATABASE_LIMIT_EXCEEDED",
                    "database project count exceeds the reconciliation limit",
                )
            revisions = list(
                connection.execute(
                    """SELECT id, project_id, parent1_id, parent2_id, root_hash
                       FROM revisions
                       ORDER BY id
                       LIMIT ?""",
                    (self.max_database_revisions + 1,),
                )
            )
            if len(revisions) > self.max_database_revisions:
                raise ValidationError(
                    "ARTIFACT_RECONCILIATION_DATABASE_LIMIT_EXCEEDED",
                    "database revision count exceeds the reconciliation limit",
                )
        except ValidationError:
            raise
        except sqlite3.Error as exc:
            raise ValidationError(
                "ARTIFACT_RECONCILIATION_DATABASE_READ_FAILED",
                "cannot read reconciliation database snapshot",
            ) from exc
        finally:
            if "connection" in locals():
                connection.rollback()
                connection.close()

        project_rows = [
            {"project_id": str(row["id"]), "name": str(row["name"])}
            for row in projects
        ]
        revision_rows = [
            {
                "revision_id": str(row["id"]),
                "project_id": str(row["project_id"]),
                "parent1_revision_id": (
                    str(row["parent1_id"])
                    if row["parent1_id"] is not None
                    else None
                ),
                "parent2_revision_id": (
                    str(row["parent2_id"])
                    if row["parent2_id"] is not None
                    else None
                ),
                "root_hash": str(row["root_hash"]),
            }
            for row in revisions
        ]
        identity = {
            "format": ARTIFACT_RECONCILIATION_DATABASE_FORMAT,
            "semantic_contract": DATABASE_SEMANTIC_INTEGRITY_CONTRACT,
            "schema_version": integrity["schema_version"],
            "projects": project_rows,
            "revisions": revision_rows,
        }
        project_names = {row["project_id"]: row["name"] for row in project_rows}
        revision_projects = {
            row["revision_id"]: project_names[row["project_id"]]
            for row in revision_rows
        }
        report = {
            "format": ARTIFACT_RECONCILIATION_DATABASE_FORMAT,
            "complete": True,
            "semantic_contract": DATABASE_SEMANTIC_INTEGRITY_CONTRACT,
            "schema_version": integrity["schema_version"],
            "location_id": self._database_location_id(path),
            "project_count": len(project_rows),
            "revision_count": len(revision_rows),
            "database_snapshot_id": self._hash_json(identity),
        }
        return _DatabaseSnapshot(report, revision_projects)

    def _inventory_snapshot(self) -> _InventorySnapshot:
        entries_remaining = self.inventory.max_entries
        family_reports: list[dict[str, Any]] = []
        identity_families: list[dict[str, Any]] = []
        records: list[dict[str, Any]] = []
        evidence: dict[tuple[str, str], dict[str, Any]] = {}

        for family in self.inventory.families:
            snapshots = self.inventory._snapshot_entries(
                family,
                remaining=entries_remaining,
            )
            entries_remaining -= len(snapshots)
            nested = self.inventory._nested_family_names(family)
            skipped_roots = {
                candidate.root
                for candidate in self.inventory.families
                if candidate.name in nested
            }
            family_records: list[dict[str, Any]] = []
            for snapshot in snapshots:
                if family.root / snapshot.name in skipped_roots:
                    continue
                record, verified = self._classify_entry(family, snapshot)
                family_records.append(record)
                if verified is not None and record["artifact_id"] is not None:
                    evidence[(family.name, record["artifact_id"])] = verified

            after = self.inventory._snapshot_entries(
                family,
                remaining=self.inventory.max_entries,
            )
            if snapshots != after:
                raise ValidationError(
                    "ARTIFACT_RECONCILIATION_CHANGED_DURING_SCAN",
                    f"retained artifact family {family.name!r} changed during scan",
                )
            family_report, family_identity = self.inventory._family_report(
                family,
                family_records,
                entries_scanned=len(snapshots),
                nested_roots=nested,
            )
            family_reports.append(family_report)
            identity_families.append(family_identity)
            records.extend(
                {"family": family.name, **record}
                for record in family_records
            )

        aggregate_counts = {
            classification: sum(
                family["counts"][classification]
                for family in family_reports
            )
            for classification in _INVENTORY_CLASSIFICATIONS
        }
        aggregate = {
            "family_count": len(family_reports),
            "entry_count": sum(
                family["entry_count"] for family in family_reports
            ),
            "entries_scanned": sum(
                family["entries_scanned"] for family in family_reports
            ),
            "counts": aggregate_counts,
        }
        report = {
            "format": RETAINED_ARTIFACT_INVENTORY_FORMAT,
            "complete": True,
            "aggregate": aggregate,
            "families": family_reports,
            "limits": {
                "families": MAX_RECONCILIATION_FAMILIES,
                "entries": self.inventory.max_entries,
                "entries_per_family": (
                    self.inventory.max_entries_per_family
                ),
                "examples_per_classification": (
                    self.inventory.max_examples
                ),
            },
            "inventory_id": self._hash_json(
                {
                    "format": RETAINED_ARTIFACT_INVENTORY_FORMAT,
                    "families": identity_families,
                }
            ),
        }
        return _InventorySnapshot(report, tuple(records), evidence)

    def _classify_entry(
        self,
        family: RetainedArtifactFamily,
        snapshot: Any,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        entry_type = self.inventory._entry_type(snapshot.mode)
        artifact_id = (
            snapshot.name
            if family.artifact_id_pattern.fullmatch(snapshot.name)
            else None
        )
        entry_id = self.inventory._entry_id(
            family.name,
            self.inventory._root_id(family),
            snapshot.name,
        )

        if entry_type in {"symlink", "special"}:
            return (
                self.inventory._entry_record(
                    entry_id=entry_id,
                    artifact_id=artifact_id,
                    entry_type=entry_type,
                    classification="unknown",
                ),
                None,
            )
        internal = self.inventory._internal_classification(snapshot.name)
        if internal is not None:
            return (
                self.inventory._entry_record(
                    entry_id=entry_id,
                    artifact_id=artifact_id,
                    entry_type=entry_type,
                    classification=internal,
                ),
                None,
            )
        if artifact_id is None:
            return (
                self.inventory._entry_record(
                    entry_id=entry_id,
                    artifact_id=None,
                    entry_type=entry_type,
                    classification="unknown",
                ),
                None,
            )
        if entry_type != "directory":
            return (
                self.inventory._entry_record(
                    entry_id=entry_id,
                    artifact_id=artifact_id,
                    entry_type=entry_type,
                    classification="corrupt",
                    error_code="ARTIFACT_ENTRY_NOT_DIRECTORY",
                ),
                None,
            )

        try:
            verified = family.verifier(artifact_id)
            if not isinstance(verified, Mapping):
                raise TypeError("artifact verifier must return a mapping")
        except Exception as exc:
            return (
                self.inventory._entry_record(
                    entry_id=entry_id,
                    artifact_id=artifact_id,
                    entry_type=entry_type,
                    classification="corrupt",
                    error_code=self._error_code(exc),
                ),
                None,
            )
        return (
            self.inventory._entry_record(
                entry_id=entry_id,
                artifact_id=artifact_id,
                entry_type=entry_type,
                classification="verified",
            ),
            dict(verified),
        )

    def _reconcile(
        self,
        database: _DatabaseSnapshot,
        inventory: _InventorySnapshot,
    ) -> dict[str, Any]:
        verified = {
            (record["family"], record["artifact_id"]): record
            for record in inventory.records
            if record["classification"] == "verified"
            and record["artifact_id"] is not None
        }
        anchors: dict[tuple[str, str], list[dict[str, str]]] = {}
        references: dict[
            tuple[str, str],
            tuple[tuple[str, str], ...],
        ] = {}
        reachable: set[tuple[str, str]] = set()
        relationship_count = 0

        for key in sorted(verified):
            evidence = inventory.evidence[key]
            artifact_anchors = self._revision_anchors(key[0], evidence)
            artifact_references = self._artifact_references(key[0], evidence)
            relationship_count += len(artifact_references)
            if relationship_count > self.max_relationships:
                raise ValidationError(
                    "ARTIFACT_RECONCILIATION_RELATIONSHIP_LIMIT_EXCEEDED",
                    "artifact relationships exceed the reconciliation limit",
                )
            anchors[key] = artifact_anchors
            references[key] = artifact_references
            if self._directly_reachable(
                key[0],
                evidence,
                artifact_anchors,
                database,
            ):
                reachable.add(key)

        changed = True
        while changed:
            changed = False
            for source in sorted(reachable):
                for target in references.get(source, ()):
                    if target in verified and target not in reachable:
                        reachable.add(target)
                        changed = True

        physical_keys = {
            (record["family"], record["artifact_id"])
            for record in inventory.records
            if record.get("artifact_id") is not None
        }
        required_by: dict[
            tuple[str, str],
            set[tuple[str, str]],
        ] = {}
        for source in sorted(reachable):
            for target in references.get(source, ()):
                if target not in verified and target not in physical_keys:
                    required_by.setdefault(target, set()).add(source)

        by_family: dict[str, list[dict[str, Any]]] = {
            family.name: [] for family in self.inventory.families
        }
        identity_by_family: dict[str, list[dict[str, Any]]] = {
            family.name: [] for family in self.inventory.families
        }

        for record in inventory.records:
            public = dict(record)
            key = (
                record["family"],
                record["artifact_id"],
            )
            if record["classification"] == "verified":
                classification = (
                    "reachable" if key in reachable else "orphaned"
                )
                public["classification"] = classification
                evidence = inventory.evidence[key]
                identity_record = {
                    **public,
                    "manifest_sha256": evidence.get("manifest_sha256"),
                    "anchors": anchors.get(key, []),
                    "references": [
                        {"family": family, "artifact_id": artifact_id}
                        for family, artifact_id in references.get(key, ())
                    ],
                }
            else:
                identity_record = dict(public)
            by_family[record["family"]].append(public)
            identity_by_family[record["family"]].append(identity_record)

        family_roots = {
            family.name: self.inventory._root_id(family)
            for family in self.inventory.families
        }
        for target, sources in sorted(required_by.items()):
            family, artifact_id = target
            record = {
                "family": family,
                "entry_id": self.inventory._entry_id(
                    family,
                    family_roots[family],
                    artifact_id,
                ),
                "artifact_id": artifact_id,
                "entry_type": "missing",
                "classification": "missing",
                "required_by_count": len(sources),
                "required_by": [
                    {
                        "family": source_family,
                        "artifact_id": source_artifact,
                    }
                    for source_family, source_artifact in sorted(sources)
                ][: self.max_examples],
            }
            by_family[family].append(record)
            identity_by_family[family].append(
                {
                    **record,
                    "required_by": [
                        {
                            "family": source_family,
                            "artifact_id": source_artifact,
                        }
                        for source_family, source_artifact in sorted(sources)
                    ],
                }
            )

        inventory_families = {
            family["family"]: family
            for family in inventory.report["families"]
        }
        family_reports: list[dict[str, Any]] = []
        identity_families: list[dict[str, Any]] = []
        for family in sorted(by_family):
            ordered = sorted(
                by_family[family],
                key=lambda item: (
                    item["classification"],
                    item.get("artifact_id") or "",
                    item["entry_id"],
                ),
            )
            identity_records = sorted(
                identity_by_family[family],
                key=lambda item: (
                    item["classification"],
                    item.get("artifact_id") or "",
                    item["entry_id"],
                ),
            )
            counts = {
                classification: sum(
                    item["classification"] == classification
                    for item in ordered
                )
                for classification in _RECONCILIATION_CLASSIFICATIONS
            }
            examples = {
                classification: [
                    self._public_record(item)
                    for item in ordered
                    if item["classification"] == classification
                ][: self.max_examples]
                for classification in _RECONCILIATION_CLASSIFICATIONS
            }
            identity = {
                "family": family,
                "root_id": family_roots[family],
                "records": identity_records,
            }
            family_reports.append(
                {
                    "family": family,
                    "root_id": family_roots[family],
                    "complete": True,
                    "entry_count": len(ordered),
                    "physical_entry_count": inventory_families[family][
                        "entry_count"
                    ],
                    "missing_entry_count": counts["missing"],
                    "counts": counts,
                    "examples": examples,
                    "family_reconciliation_id": self._hash_json(identity),
                }
            )
            identity_families.append(identity)

        aggregate_counts = {
            classification: sum(
                family["counts"][classification]
                for family in family_reports
            )
            for classification in _RECONCILIATION_CLASSIFICATIONS
        }
        aggregate = {
            "family_count": len(family_reports),
            "physical_entry_count": inventory.report["aggregate"][
                "entry_count"
            ],
            "missing_entry_count": aggregate_counts["missing"],
            "catalog_entry_count": sum(
                family["entry_count"] for family in family_reports
            ),
            "relationship_count": relationship_count,
            "counts": aggregate_counts,
        }
        return {
            "format": ARTIFACT_RECONCILIATION_FORMAT,
            "complete": True,
            "database": database.report,
            "inventory": {
                "format": inventory.report["format"],
                "inventory_id": inventory.report["inventory_id"],
                "aggregate": inventory.report["aggregate"],
            },
            "aggregate": aggregate,
            "families": family_reports,
            "limits": {
                "database_projects": self.max_database_projects,
                "database_revisions": self.max_database_revisions,
                "artifact_relationships": self.max_relationships,
                "examples_per_classification": self.max_examples,
            },
            "_identity_families": identity_families,
        }

    @staticmethod
    def _revision_anchors(
        family: str,
        evidence: Mapping[str, Any],
    ) -> list[dict[str, str]]:
        if family in {"committed_builds", "test_runs", "test_batches"}:
            project = evidence.get("project")
            revision_id = evidence.get("revision_id")
            if isinstance(project, str) and isinstance(revision_id, str):
                return [{"project": project, "revision_id": revision_id}]
            return []
        if family in {
            "candidate_builds",
            "candidate_test_qualifications",
        }:
            subject = evidence.get("subject")
            if not isinstance(subject, Mapping):
                return []
            project = subject.get("project")
            if not isinstance(project, str):
                return []
            anchors = []
            for field in (
                "base_revision_id",
                "target_head_revision_id",
                "source_head_revision_id",
            ):
                revision_id = subject.get(field)
                if not isinstance(revision_id, str):
                    return []
                anchors.append(
                    {"project": project, "revision_id": revision_id}
                )
            return anchors
        if family == "tested_merge_attestations":
            revision = evidence.get("merged_revision")
            if not isinstance(revision, Mapping):
                return []
            project = revision.get("project")
            revision_id = revision.get("revision_id")
            if isinstance(project, str) and isinstance(revision_id, str):
                return [{"project": project, "revision_id": revision_id}]
        return []

    @staticmethod
    def _artifact_references(
        family: str,
        evidence: Mapping[str, Any],
    ) -> tuple[tuple[str, str], ...]:
        references: set[tuple[str, str]] = set()
        if family == "test_runs":
            build_id = evidence.get("build_id")
            if isinstance(build_id, str):
                references.add(("committed_builds", build_id))
        elif family == "test_batches":
            results = evidence.get("results")
            if isinstance(results, list):
                for result in results:
                    if not isinstance(result, Mapping):
                        continue
                    run_id = result.get("run_id")
                    if isinstance(run_id, str):
                        references.add(("test_runs", run_id))
        elif family == "candidate_test_qualifications":
            builds = evidence.get("builds")
            if isinstance(builds, list):
                for build in builds:
                    if not isinstance(build, Mapping):
                        continue
                    build_id = build.get("build_id")
                    if isinstance(build_id, str):
                        references.add(("candidate_builds", build_id))
        elif family == "tested_merge_attestations":
            qualification_id = evidence.get("qualification_id")
            if isinstance(qualification_id, str):
                references.add(
                    ("candidate_test_qualifications", qualification_id)
                )
        return tuple(sorted(references))

    @staticmethod
    def _directly_reachable(
        family: str,
        evidence: Mapping[str, Any],
        anchors: list[dict[str, str]],
        database: _DatabaseSnapshot,
    ) -> bool:
        if family == "database_backups":
            source = evidence.get("source")
            return (
                isinstance(source, Mapping)
                and source.get("location_id")
                == database.report["location_id"]
            )
        if not anchors:
            return False
        return all(
            database.revision_projects.get(anchor["revision_id"])
            == anchor["project"]
            for anchor in anchors
        )

    @staticmethod
    def _public_record(record: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in record.items()
            if key != "family" and value is not None
        }

    @staticmethod
    def _database_location_id(path: Path) -> str:
        encoded = (
            b"weave-database-location-v1\0"
            + str(path.resolve()).encode("utf-8")
        )
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _error_code(exc: Exception) -> str:
        if isinstance(exc, ValidationError):
            return exc.code
        if isinstance(exc, ArtifactIntegrityError):
            return "ARTIFACT_INTEGRITY_ERROR"
        if isinstance(exc, NotFoundError):
            return "NOT_FOUND"
        if isinstance(exc, OSError):
            return "OS_ERROR"
        if isinstance(exc, TypeError):
            return "INVALID_ARTIFACT_VERIFIER_RESULT"
        return type(exc).__name__

    @staticmethod
    def _hash_json(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _validate_positive_limit(name: str, value: Any) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")


__all__ = [
    "ARTIFACT_RECONCILIATION_DATABASE_FORMAT",
    "ARTIFACT_RECONCILIATION_FORMAT",
    "MAX_RECONCILIATION_DATABASE_PROJECTS",
    "MAX_RECONCILIATION_DATABASE_REVISIONS",
    "MAX_RECONCILIATION_RELATIONSHIPS",
    "ArtifactReconciliationService",
]
