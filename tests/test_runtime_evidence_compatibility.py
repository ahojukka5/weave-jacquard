from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from weave_frontend.runtime_evidence_compatibility import (
    RUNTIME_IDENTITY_COMPATIBILITY_DIFF_FORMAT,
    RUNTIME_IDENTITY_FORMAT,
    SERVICE_GRAPH_COMPATIBILITY_DIFF_FORMAT,
    SERVICE_GRAPH_FORMAT,
    RuntimeEvidenceCompatibilityError,
    compare_runtime_evidence,
    compare_runtime_identities,
    compare_service_graphs,
)


def _identity(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _service_graph(
    *services: dict[str, object],
    initialized: list[str] | None = None,
) -> dict[str, object]:
    ordered = sorted(services, key=lambda item: str(item["name"]))
    payload = {
        "format": SERVICE_GRAPH_FORMAT,
        "service_count": len(ordered),
        "services": ordered,
    }
    result: dict[str, object] = {
        **payload,
        "service_graph_id": _identity(payload),
    }
    if initialized is not None:
        result["initialized_service_count"] = len(initialized)
        result["initialized_services"] = sorted(initialized)
    return result


def _service(
    name: str,
    *,
    origin: str | None = None,
    depends_on: list[str] | None = None,
) -> dict[str, object]:
    return {
        "name": name,
        "origin": origin or f"example.{name}",
        "depends_on": sorted(depends_on or []),
    }


def _runtime_identity() -> dict[str, object]:
    payload = {
        "format": RUNTIME_IDENTITY_FORMAT,
        "jacquard": {
            "version": "0.1.0",
            "application_id": "a" * 64,
            "tool_manifest_id": "b" * 64,
            "tool_count": 2,
            "capability_count": 1,
        },
        "python": {
            "implementation": "CPython",
            "version": "3.12.3",
            "executable_sha256": "c" * 64,
        },
        "mcp": {"version": "1.29.0"},
        "database": {
            "schema_version": 7,
            "busy_timeout_ms": 5000,
            "journal_mode": "wal",
            "foreign_keys": True,
            "location_id": "d" * 64,
        },
        "compiler": {
            "available": True,
            "binary": {
                "available": True,
                "bytes": 1024,
                "sha256": "e" * 64,
                "error": None,
            },
            "version": "weavec 1.0",
            "error": None,
        },
        "sandbox": {
            "available": True,
            "capabilities": {"backend": "test"},
            "bubblewrap_binary": None,
            "prlimit_binary": None,
            "error": None,
        },
        "configuration": {
            "variables": ["WEAVE_DB"],
            "configured_variables": ["WEAVE_DB"],
            "value_ids": {"WEAVE_DB": "f" * 64},
            "values_redacted": True,
        },
    }
    return {
        **payload,
        "runtime_id": _identity(payload),
    }


def test_identical_service_graph_ignores_initialized_state() -> None:
    old = _service_graph(
        _service("compiler", depends_on=["workspace"]),
        _service("workspace"),
        initialized=[],
    )
    new = _service_graph(
        _service("compiler", depends_on=["workspace"]),
        _service("workspace"),
        initialized=["workspace"],
    )

    first = compare_service_graphs(old, new)
    second = compare_service_graphs(old, new)

    assert first == second
    assert first["format"] == SERVICE_GRAPH_COMPATIBILITY_DIFF_FORMAT
    assert first["classification"] == "identity-only"
    assert first["change_count"] == 0
    assert first["changes"] == []


def test_service_graph_topology_changes_require_review() -> None:
    old = _service_graph(_service("workspace"))
    new = _service_graph(
        _service("compiler", depends_on=["workspace"]),
        _service("workspace"),
    )

    report = compare_service_graphs(old, new)

    assert report["classification"] == "behavior-review-required"
    assert report["changes"] == [
        {
            "pointer": "/services/compiler",
            "classification": "behavior-review-required",
            "kind": "service-added",
            "old": None,
            "new": _service("compiler", depends_on=["workspace"]),
        }
    ]


def test_service_origin_and_dependencies_are_reported_separately() -> None:
    old = _service_graph(
        _service("compiler", origin="old.factory", depends_on=["workspace"]),
        _service("workspace"),
    )
    new = _service_graph(
        _service("compiler", origin="new.factory"),
        _service("workspace"),
    )

    report = compare_service_graphs(old, new)

    assert [change["pointer"] for change in report["changes"]] == [
        "/services/compiler/depends_on",
        "/services/compiler/origin",
    ]
    assert {change["kind"] for change in report["changes"]} == {
        "service-dependencies-changed",
        "service-origin-changed",
    }


def test_service_graph_identity_mismatch_fails_closed() -> None:
    graph = _service_graph(_service("workspace"))
    graph["service_graph_id"] = "0" * 64

    with pytest.raises(
        RuntimeEvidenceCompatibilityError,
        match="service_graph_id does not match",
    ):
        compare_service_graphs(graph, graph)


def test_runtime_identity_reports_exact_component_pointer() -> None:
    old = _runtime_identity()
    new = deepcopy(old)
    new["database"]["schema_version"] = 8
    payload = {key: value for key, value in new.items() if key != "runtime_id"}
    new["runtime_id"] = _identity(payload)

    report = compare_runtime_identities(old, new)

    assert report["format"] == RUNTIME_IDENTITY_COMPATIBILITY_DIFF_FORMAT
    assert report["classification"] == "behavior-review-required"
    assert report["changes"] == [
        {
            "pointer": "/database/schema_version",
            "classification": "behavior-review-required",
            "kind": "runtime-value-changed",
            "old": 7,
            "new": 8,
        }
    ]


def test_identical_runtime_identity_is_empty_and_deterministic() -> None:
    runtime = _runtime_identity()

    first = compare_runtime_identities(runtime, runtime)
    second = compare_runtime_identities(runtime, runtime)

    assert first == second
    assert first["classification"] == "identity-only"
    assert first["change_count"] == 0


def test_runtime_evidence_families_cannot_be_mixed() -> None:
    with pytest.raises(
        RuntimeEvidenceCompatibilityError,
        match="evidence families differ",
    ):
        compare_runtime_evidence(
            _service_graph(_service("workspace")),
            _runtime_identity(),
        )
