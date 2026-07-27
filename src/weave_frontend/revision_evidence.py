"""Bounded verified evidence discovery for one exact immutable project revision."""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .errors import ArtifactIntegrityError, NotFoundError, ValidationError
from .revision_evidence_graph import (
    deduplicate_edges,
    deduplicate_nodes,
    evidence_graph,
    evidence_matches_revision,
    revision_node,
)

REVISION_EVIDENCE_PAGE_FORMAT = "weave-revision-evidence-page-v1"
REVISION_EVIDENCE_CATALOG_FORMAT = "weave-revision-evidence-catalog-v1"
EVIDENCE_ID = re.compile(r"^[0-9a-f]{32}$")
CATALOG_ID = re.compile(r"^[0-9a-f]{64}$")
EVIDENCE_KINDS = {
    "build",
    "test_run",
    "test_batch",
    "tested_merge_attestation",
}
MAX_EVIDENCE_PAGE = 100
MAX_EVIDENCE_SCAN = 200


@dataclass(frozen=True)
class _Store:
    kind: str
    root: Path
    getter: Callable[[str], dict[str, Any]]
    manifest_name: str


class RevisionEvidenceService:
    """Discover retained evidence through each artifact service's verifier."""

    def __init__(
        self,
        workspace: Any,
        builds: Any,
        runs: Any,
        batches: Any,
        qualifications: Any,
        attestations: Any,
    ) -> None:
        self.workspace = workspace
        self.qualifications = qualifications
        self._stores = {
            "build": _Store(
                "build",
                Path(builds.build_root).resolve(),
                builds.get,
                "manifest.json",
            ),
            "test_run": _Store(
                "test_run",
                Path(runs.run_root).resolve(),
                runs.get,
                "run-manifest.json",
            ),
            "test_batch": _Store(
                "test_batch",
                Path(batches.batch_root).resolve(),
                batches.get,
                "batch-manifest.json",
            ),
            "tested_merge_attestation": _Store(
                "tested_merge_attestation",
                Path(attestations.attestation_root).resolve(),
                attestations.get,
                "attestation.json",
            ),
        }

    def page(
        self,
        project: str,
        revision_id: str,
        kind: str,
        *,
        start_after_id: str | None = None,
        catalog_id: str | None = None,
        limit: int = 25,
        scan_limit: int = 100,
    ) -> dict[str, Any]:
        """Return one stable page of verified evidence nodes and typed edges."""

        revision = self._revision(project, revision_id)
        store = self._store(kind)
        self._validate_bounds(limit, scan_limit)
        self._validate_start_after(start_after_id)
        self._validate_catalog_id(catalog_id)

        members = self._catalog_members(store)
        effective_catalog_id = self.workspace.db.hash_value(
            {
                "format": REVISION_EVIDENCE_CATALOG_FORMAT,
                "project": project,
                "revision_id": revision_id,
                "kind": kind,
                "members": members,
            }
        )
        if catalog_id is not None and catalog_id != effective_catalog_id:
            raise ValidationError(
                "STALE_REVISION_EVIDENCE_CATALOG",
                "retained evidence membership changed since the requested catalog",
            )

        start_index = (
            bisect.bisect_right(members, start_after_id)
            if start_after_id is not None
            else 0
        )
        scanned_ids = members[start_index : start_index + scan_limit]
        nodes = [revision_node(revision)]
        edges: list[dict[str, str]] = []
        rejected: list[dict[str, str]] = []
        matched_evidence_count = 0
        consumed_count = 0

        for consumed_count, evidence_id in enumerate(scanned_ids, start=1):
            try:
                evidence = store.getter(evidence_id)
                if not evidence_matches_revision(kind, evidence, project, revision_id):
                    continue
                evidence_nodes, evidence_edges = evidence_graph(
                    kind,
                    evidence,
                    revision_id,
                    qualifications=self.qualifications,
                )
            except (ArtifactIntegrityError, NotFoundError, ValidationError, OSError) as exc:
                rejected.append(
                    {
                        "evidence_id": evidence_id,
                        "error_code": self._error_code(exc),
                    }
                )
                continue
            nodes.extend(evidence_nodes)
            edges.extend(evidence_edges)
            matched_evidence_count += 1
            if matched_evidence_count >= limit:
                break

        consumed_ids = scanned_ids[:consumed_count]
        next_index = start_index + consumed_count
        has_more = next_index < len(members)
        next_after_id = consumed_ids[-1] if has_more and consumed_ids else None
        graph_nodes = deduplicate_nodes(nodes)
        graph_edges = deduplicate_edges(edges)
        payload = {
            "format": REVISION_EVIDENCE_PAGE_FORMAT,
            "catalog_format": REVISION_EVIDENCE_CATALOG_FORMAT,
            "project": project,
            "revision": revision,
            "subject_node_id": f"revision:{revision_id}",
            "kind": kind,
            "catalog_id": effective_catalog_id,
            "catalog_scope": f"{kind}-root-membership",
            "catalog_member_count": len(members),
            "start_after_id": start_after_id,
            "limit": limit,
            "scan_limit": scan_limit,
            "scanned_member_count": consumed_count,
            "matched_evidence_count": matched_evidence_count,
            "returned_node_count": len(graph_nodes),
            "returned_edge_count": len(graph_edges),
            "rejected_evidence_count": len(rejected),
            "has_more": has_more,
            "next_after_id": next_after_id,
            "nodes": graph_nodes,
            "edges": graph_edges,
            "rejected": rejected,
            "ordering": "lexical evidence ID within one exact live store catalog",
            "edge_note": (
                "edges may reference typed nodes discoverable from another evidence-kind page"
            ),
            "interpretation": {
                "retained_evidence_only": True,
                "claims_complete_coverage": False,
                "claims_unretained_preflight_history": False,
                "claims_policy_admission": False,
                "claims_approval_or_readiness": False,
            },
        }
        payload["page_id"] = self.workspace.db.hash_value(payload)
        return payload

    def _catalog_members(self, store: _Store) -> list[str]:
        try:
            entries = list(store.root.iterdir())
        except OSError as exc:
            raise ValidationError(
                "REVISION_EVIDENCE_CATALOG_UNAVAILABLE",
                f"cannot enumerate retained {store.kind} evidence: {exc}",
            ) from exc

        members: list[str] = []
        for entry in entries:
            try:
                if not EVIDENCE_ID.fullmatch(entry.name) or entry.is_symlink():
                    continue
                manifest = entry / store.manifest_name
                is_member = (
                    entry.is_dir()
                    and manifest.is_file()
                    and not manifest.is_symlink()
                )
            except OSError:
                continue
            if is_member:
                members.append(entry.name)
        return sorted(members)

    def _revision(self, project: str, revision_id: str) -> dict[str, Any]:
        if not isinstance(revision_id, str) or not revision_id:
            raise ValidationError(
                "INVALID_REVISION_ID",
                "revision_id must be a non-empty string",
            )
        row = self.workspace.db.connection.execute(
            """SELECT r.id, r.parent1_id, r.parent2_id, r.root_hash, r.message,
                      r.author, r.created_at
               FROM revisions r
               JOIN projects p ON p.id = r.project_id
               WHERE r.id = ? AND p.name = ?""",
            (revision_id, project),
        ).fetchone()
        if row is None:
            raise NotFoundError(
                f"revision {revision_id!r} does not belong to project {project!r}"
            )
        return {
            "revision_id": str(row["id"]),
            "parent1_revision_id": row["parent1_id"],
            "parent2_revision_id": row["parent2_id"],
            "root_hash": str(row["root_hash"]),
            "message": str(row["message"]),
            "author": str(row["author"]),
            "created_at": str(row["created_at"]),
        }

    def _store(self, kind: str) -> _Store:
        if not isinstance(kind, str) or kind not in EVIDENCE_KINDS:
            raise ValidationError(
                "INVALID_REVISION_EVIDENCE_KIND",
                f"kind must be one of {sorted(EVIDENCE_KINDS)}",
            )
        return self._stores[kind]

    @staticmethod
    def _validate_bounds(limit: Any, scan_limit: Any) -> None:
        for name, value, maximum in (
            ("limit", limit, MAX_EVIDENCE_PAGE),
            ("scan_limit", scan_limit, MAX_EVIDENCE_SCAN),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 1 <= value <= maximum
            ):
                raise ValidationError(
                    "INVALID_REVISION_EVIDENCE_LIMIT",
                    f"{name} must be an integer between 1 and {maximum}",
                )
        if scan_limit < limit:
            raise ValidationError(
                "INVALID_REVISION_EVIDENCE_LIMIT",
                "scan_limit must be greater than or equal to limit",
            )

    @staticmethod
    def _validate_start_after(value: Any) -> None:
        if value is not None and (
            not isinstance(value, str) or not EVIDENCE_ID.fullmatch(value)
        ):
            raise ValidationError(
                "INVALID_REVISION_EVIDENCE_CURSOR",
                "start_after_id must be 32 lowercase hexadecimal characters or null",
            )

    @staticmethod
    def _validate_catalog_id(value: Any) -> None:
        if value is not None and (
            not isinstance(value, str) or not CATALOG_ID.fullmatch(value)
        ):
            raise ValidationError(
                "INVALID_REVISION_EVIDENCE_CATALOG_ID",
                "catalog_id must be 64 lowercase hexadecimal characters or null",
            )

    @staticmethod
    def _error_code(exc: Exception) -> str:
        if isinstance(exc, ValidationError):
            return exc.code
        if isinstance(exc, NotFoundError):
            return "NOT_FOUND"
        if isinstance(exc, ArtifactIntegrityError):
            return "ARTIFACT_INTEGRITY_ERROR"
        return type(exc).__name__
