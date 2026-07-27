"""Pure node and edge rendering for verified revision evidence."""

from __future__ import annotations

from typing import Any


def revision_node(revision: dict[str, Any]) -> dict[str, Any]:
    """Return the canonical subject node for one immutable revision."""

    revision_id = str(revision["revision_id"])
    return {
        "node_id": f"revision:{revision_id}",
        "kind": "revision",
        **revision,
    }


def evidence_graph(
    kind: str,
    evidence: dict[str, Any],
    revision_id: str,
    *,
    qualifications: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Render one already-verified store member without reading the filesystem."""

    if kind == "build":
        return _build_graph(evidence, revision_id)
    if kind == "test_run":
        return _run_graph(evidence, revision_id)
    if kind == "test_batch":
        return _batch_graph(evidence, revision_id)
    if kind == "tested_merge_attestation":
        return _attestation_graph(
            evidence,
            revision_id,
            qualifications=qualifications,
        )
    raise AssertionError(f"unsupported evidence kind {kind!r}")


def evidence_matches_revision(
    kind: str,
    evidence: dict[str, Any],
    project: str,
    revision_id: str,
) -> bool:
    """Return whether one verified manifest is evidence about the selected revision."""

    if kind == "tested_merge_attestation":
        revision = evidence.get("merged_revision")
        return (
            isinstance(revision, dict)
            and revision.get("project") == project
            and revision.get("revision_id") == revision_id
        )
    return evidence.get("project") == project and evidence.get("revision_id") == revision_id


def deduplicate_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Preserve first occurrence order while enforcing one node per typed identity."""

    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node in nodes:
        node_id = str(node["node_id"])
        if node_id in seen:
            continue
        seen.add(node_id)
        result.append(node)
    return result


def deduplicate_edges(edges: list[dict[str, str]]) -> list[dict[str, str]]:
    """Preserve first occurrence order for typed graph edges."""

    result: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for edge in edges:
        key = (edge["from"], edge["relation"], edge["to"])
        if key in seen:
            continue
        seen.add(key)
        result.append(edge)
    return result


def _build_graph(
    evidence: dict[str, Any],
    revision_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    build_id = str(evidence["build_id"])
    node_id = f"build:{build_id}"
    node = {
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
    edge = {
        "from": node_id,
        "relation": "built_from_revision",
        "to": f"revision:{revision_id}",
    }
    return [node], [edge]


def _run_graph(
    evidence: dict[str, Any],
    revision_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    run_id = str(evidence["run_id"])
    build_id = str(evidence["build_id"])
    node_id = f"test_run:{run_id}"
    node = {
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
    return [node], [
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
    ]


def _batch_graph(
    evidence: dict[str, Any],
    revision_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    batch_id = str(evidence["batch_id"])
    node_id = f"test_batch:{batch_id}"
    node = {
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
        "detail": {"tool": "test_batch_get", "arguments": {"batch_id": batch_id}},
    }
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
    return [node], edges


def _attestation_graph(
    evidence: dict[str, Any],
    revision_id: str,
    *,
    qualifications: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    attestation_id = str(evidence["attestation_id"])
    qualification_id = str(evidence["qualification_id"])
    qualification = qualifications.get(qualification_id)
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
