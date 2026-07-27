"""Bounded verified evidence graphs for one exact immutable project revision."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .errors import ArtifactIntegrityError, NotFoundError, ValidationError

REVISION_EVIDENCE_PAGE_FORMAT = "weave-revision-evidence-page-v1"
REVISION_EVIDENCE_CATALOG_FORMAT = "weave-revision-evidence-catalog-v1"
EVIDENCE_ID = re.compile(r"^[0-9a-f]{32}$")
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
        self.builds = builds
        self.runs = runs
        self.batches = batches
        self.qualifications = qualifications
        self.attestations = attestations
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
        """Return one stable bounded page of verified evidence nodes and edges."""

        revision = self._revision(project, revision_id)
        store = self._store(kind)
        self._validate_bounds(limit, scan_limit)
        self._validate_optional_id("start_after_id", start_after_id)
        self._validate_optional_id("catalog_id", catalog_id, pattern=None)

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
        start_index = self._start_index(members, start_after_id)
        scanned_ids = members[start_index : start_index + scan_limit]
        nodes = [self._revision_node(revision)]
        edges: list[dict[str, str]] = []
        rejected: list[dict[str, str]] = []
        matched = 0
        for evidence_id in scanned_ids:
            try:
                evidence = store.getter(evidence_id)
                if not self._matches(kind, evidence, project, revision_id):
                    continue
                evidence_nodes, evidence_edges = self._graph(kind, evidence, revision_id)
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
            matched += 1
            if matched >= limit:
                break

        consumed_count = self._consumed_count(
            scanned_ids,
            nodes,
            rejected,
            kind=kind,
            project=project,
            revision_id=revision_id,
            limit=limit,
            store=store,
        )
        consumed_ids = scanned_ids[:consumed_count]
        next_index = start_index + consumed_count
        has_more = next_index < len(members)
        next_after_id = consumed_ids[-1] if has_more and consumed_ids else None
        payload = {
            "format": REVISION_EVIDENCE_PAGE_FORMAT,
            "project": project,
            "revision": revision,
            "subject_node_id": f"revision:{revision_id}",
            "kind": kind,
            "catalog_id": effective_catalog_id,
            "catalog_member_count": len(members),
            "start_after_id": start_after_id,
            "limit": limit,
            "scan_limit": scan_limit,
            "scanned_member_count": consumed_count,
            "matched_evidence_count": len(nodes) - 1,
            "rejected_evidence_count": len(rejected),
            "has_more": has_more,
            "next_after_id": next_after_id,
            "nodes": self._deduplicate_nodes(nodes),
            "edges": self._deduplicate_edges(edges),
            "rejected": rejected,
            "ordering": "lexical evidence ID within one exact live store catalog",
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

    def _graph(
        self,
        kind: str,
        evidence: dict[str, Any],
        revision_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        if kind == "build":
            return self._build_graph(evidence, revision_id)
        if kind == "test_run":
            return self._run_graph(evidence, revision_id)
        if kind == "test_batch":
            return self._batch_graph(evidence, revision_id)
        return self._attestation_graph(evidence, revision_id)

    @staticmethod
    def _build_graph(
        evidence: dict[str, Any],
        revision_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        build_id = str(evidence["build_id"])
        node_id = f"build:{build_id}"
        return (
            [
                {
                    "node_id": node_id,
                    "kind": "build",
                    "evidence_id": build_id,
                    "status": evidence.get("status"),
                    "project": evidence.get("project"),
                    "revision_id": evidence.get("revision_id"),
                    "document": evidence.get("document"),
                    "documents": list(evidence.get("documents", [])),
                    "target": evidence.get("target"),
                    "compiler_sha256": evidence.get("compiler_sha256"),
                    "manifest_sha256": evidence.get("manifest_sha256"),
                    "detail": {"tool": "build_get", "arguments": {"build_id": build_id}},
                }
            ],
            [
                {
                    "from": node_id,
                    "relation": "built_from_revision",
                    "to": f"revision:{revision_id}",
                }
            ],
        )

    @staticmethod
    def _run_graph(
        evidence: dict[str, Any],
        revision_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        run_id = str(evidence["run_id"])
        build_id = str(evidence["build_id"])
        node_id = f"test_run:{run_id}"
        return (
            [
                {
                    "node_id": node_id,
                    "kind": "test_run",
                    "evidence_id": run_id,
                    "status": evidence.get("status"),
                    "passed": evidence.get("passed"),
                    "project": evidence.get("project"),
                    "revision_id": evidence.get("revision_id"),
                    "test_target": evidence.get("test_target"),
                    "definition_hash": evidence.get("definition_hash"),
                    "build_id": build_id,
                    "sandbox_policy_hash": evidence.get("sandbox", {}).get("policy_hash"),
                    "manifest_sha256": evidence.get("manifest_sha256"),
                    "detail": {"tool": "test_run_get", "arguments": {"run_id": run_id}},
                }
            ],
            [
                {
                    "from": node_id,
                    "relation": "executed_revision",
                    "to": f"revision:{revision_id}",
                },
                {
                    "from": node_id,
                    "relation": "used_build",
                    "to": f"build:{build_id}",
                },
            ],
        )

    @staticmethod
    def _batch_graph(
        evidence: dict[str, Any],
        revision_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        batch_id = str(evidence["batch_id"])
        node_id = f"test_batch:{batch_id}"
        edges = [
            {
                "from": node_id,
                "relation": "qualified_revision",
                "to": f"revision:{revision_id}",
            }
        ]
        for result in evidence.get("results", []):
            run_id = result.get("run_id")
            if isinstance(run_id, str):
                edges.append(
                    {
                        "from": node_id,
                        "relation": "contains_run",
                        "to": f"test_run:{run_id}",
                    }
                )
        return (
            [
                {
                    "node_id": node_id,
                    "kind": "test_batch",
                    "evidence_id": batch_id,
                    "status": evidence.get("status"),
                    "all_passed": evidence.get("all_passed"),
                    "project": evidence.get("project"),
                    "revision_id": evidence.get("revision_id"),
                    "test_targets": list(evidence.get("test_targets", [])),
                    "selected_test_count": evidence.get("selected_test_count"),
                    "passed_test_count": evidence.get("passed_test_count"),
                    "failed_test_count": evidence.get("failed_test_count"),
                    "error_test_count": evidence.get("error_test_count"),
                    "sandbox_policy_hash": evidence.get("sandbox", {}).get("policy_hash"),
                    "manifest_sha256": evidence.get("manifest_sha256"),
                    "detail": {
                        "tool": "test_batch_get",
                        "arguments": {"batch_id": batch_id},
                    },
                }
            ],
            edges,
        )

    def _attestation_graph(
        self,
        evidence: dict[str, Any],
        revision_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        attestation_id = str(evidence["attestation_id"])
        qualification_id = str(evidence["qualification_id"])
        qualification = self.qualifications.get(qualification_id)
        attestation_node = f"tested_merge_attestation:{attestation_id}"
        qualification_node = f"merge_candidate_qualification:{qualification_id}"
        nodes = [
            {
                "node_id": attestation_node,
                "kind": "tested_merge_attestation",
                "evidence_id": attestation_id,
                "state_identity_verified": evidence.get("state_identity_verified"),
                "qualification_status": evidence.get("qualification_status"),
                "all_selected_tests_passed": evidence.get("all_selected_tests_passed"),
                "qualification_id": qualification_id,
                "merged_revision_id": revision_id,
                "manifest_sha256": evidence.get("manifest_sha256"),
                "detail": {
                    "tool": "tested_merge_attestation_get",
                    "arguments": {"attestation_id": attestation_id},
                },
            },
            {
                "node_id": qualification_node,
                "kind": "merge_candidate_qualification",
                "evidence_id": qualification_id,
                "status": qualification.get("status"),
                "all_passed": qualification.get("all_passed"),
                "subject": qualification.get("subject"),
                "test_targets": list(qualification.get("test_targets", [])),
                "selected_test_count": qualification.get("selected_test_count"),
                "passed_test_count": qualification.get("passed_test_count"),
                "failed_test_count": qualification.get("failed_test_count"),
                "error_test_count": qualification.get("error_test_count"),
                "manifest_sha256": qualification.get("manifest_sha256"),
                "detail": {
                    "tool": "merge_candidate_test_batch_get",
                    "arguments": {"qualification_id": qualification_id},
                },
            },
        ]
        edges = [
            {
                "from": attestation_node,
                "relation": "attests_revision_state",
                "to": f"revision:{revision_id}",
            },
            {
                "from": attestation_node,
                "relation": "binds_qualification",
                "to": qualification_node,
            },
        ]
        for build in qualification.get("builds", []):
            build_id = build.get("build_id")
            if not isinstance(build_id, str):
                continue
            candidate_node = f"merge_candidate_build:{build_id}"
            nodes.append(
                {
                    "node_id": candidate_node,
                    "kind": "merge_candidate_build",
                    "evidence_id": build_id,
                    "status": build.get("status"),
                    "build_target": build.get("build_target"),
                    "build_input_hash": build.get("build_input_hash"),
                    "manifest_sha256": build.get("manifest_sha256"),
                    "detail": {
                        "tool": "merge_candidate_build_get",
                        "arguments": {"build_id": build_id},
                    },
                }
            )
            edges.append(
                {
                    "from": qualification_node,
                    "relation": "used_candidate_build",
                    "to": candidate_node,
                }
            )
        return nodes, edges

    @staticmethod
    def _matches(
        kind: str,
        evidence: dict[str, Any],
        project: str,
        revision_id: str,
    ) -> bool:
        if kind == "tested_merge_attestation":
            revision = evidence.get("merged_revision")
            return (
                isinstance(revision, dict)
                and revision.get("project") == project
                and revision.get("revision_id") == revision_id
            )
        return evidence.get("project") == project and evidence.get("revision_id") == revision_id

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

    @staticmethod
    def _revision_node(revision: dict[str, Any]) -> dict[str, Any]:
        revision_id = str(revision["revision_id"])
        return {
            "node_id": f"revision:{revision_id}",
            "kind": "revision",
            **revision,
        }

    def _catalog_members(self, store: _Store) -> list[str]:
        members = []
        try:
            entries = sorted(store.root.iterdir(), key=lambda path: path.name)
        except FileNotFoundError:
            return []
        for path in entries:
            if path.is_symlink() or not path.is_dir():
                continue
            if not EVIDENCE_ID.fullmatch(path.name):
                continue
            members.append(path.name)
        return members

    @staticmethod
    def _store(kind: str) -> _Store:
        raise AssertionError("instance store lookup was not bound")

    def _store(self, kind: str) -> _Store:  # type: ignore[no-redef]
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
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
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
    def _validate_optional_id(
        name: str,
        value: Any,
        *,
        pattern: re.Pattern[str] | None = EVIDENCE_ID,
    ) -> None:
        if value is None:
            return
        if not isinstance(value, str) or not value or (pattern is not None and not pattern.fullmatch(value)):
            raise ValidationError(
                "INVALID_REVISION_EVIDENCE_CURSOR",
                f"{name} must be a valid non-empty evidence identity or null",
            )

    @staticmethod
    def _start_index(members: list[str], start_after_id: str | None) -> int:
        if start_after_id is None:
            return 0
        try:
            return members.index(start_after_id) + 1
        except ValueError as exc:
            raise ValidationError(
                "INVALID_REVISION_EVIDENCE_CURSOR",
                "start_after_id must identify a member of the current catalog",
            ) from exc

    @staticmethod
    def _error_code(exc: Exception) -> str:
        if isinstance(exc, ValidationError):
            return exc.code
        if isinstance(exc, NotFoundError):
            return "NOT_FOUND"
        if isinstance(exc, ArtifactIntegrityError):
            return "ARTIFACT_INTEGRITY_ERROR"
        return type(exc).__name__

    @staticmethod
    def _deduplicate_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for node in nodes:
            node_id = str(node["node_id"])
            if node_id in seen:
                continue
            seen.add(node_id)
            result.append(node)
        return result

    @staticmethod
    def _deduplicate_edges(edges: list[dict[str, str]]) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for edge in edges:
            key = (edge["from"], edge["relation"], edge["to"])
            if key in seen:
                continue
            seen.add(key)
            result.append(edge)
        return result

    def _consumed_count(
        self,
        scanned_ids: list[str],
        nodes: list[dict[str, Any]],
        rejected: list[dict[str, str]],
        *,
        kind: str,
        project: str,
        revision_id: str,
        limit: int,
        store: _Store,
    ) -> int:
        del nodes, rejected
        matched = 0
        for index, evidence_id in enumerate(scanned_ids, start=1):
            try:
                evidence = store.getter(evidence_id)
            except (ArtifactIntegrityError, NotFoundError, ValidationError, OSError):
                continue
            if self._matches(kind, evidence, project, revision_id):
                matched += 1
                if matched >= limit:
                    return index
        return len(scanned_ids)
