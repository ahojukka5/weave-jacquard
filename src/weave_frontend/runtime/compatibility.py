"""Semantic compatibility diffing for service-graph and runtime evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

SERVICE_GRAPH_FORMAT = "weave-jacquard-runtime-service-graph-v1"
RUNTIME_IDENTITY_FORMAT = "weave-jacquard-runtime-identity-v1"
SERVICE_GRAPH_COMPATIBILITY_DIFF_FORMAT = (
    "weave-jacquard-service-graph-compatibility-diff-v1"
)
RUNTIME_IDENTITY_COMPATIBILITY_DIFF_FORMAT = (
    "weave-jacquard-runtime-identity-compatibility-diff-v1"
)
_CLASSIFICATION_ORDER = {
    "identity-only": 0,
    "behavior-review-required": 1,
}


class RuntimeEvidenceCompatibilityError(ValueError):
    """Raised when runtime evidence cannot be compared safely."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _fragment(value: Any) -> Any:
    encoded = _canonical_json(value)
    if len(encoded) <= 512:
        return value
    return {
        "sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        "truncated": True,
    }


def _change(pointer: str, kind: str, old: Any, new: Any) -> dict[str, Any]:
    return {
        "pointer": pointer,
        "classification": "behavior-review-required",
        "kind": kind,
        "old": _fragment(old),
        "new": _fragment(new),
    }


def _report(report_format: str, changes: list[dict[str, Any]]) -> dict[str, Any]:
    changes.sort(key=lambda item: (item["pointer"], item["kind"]))
    classification = "identity-only"
    if changes:
        classification = max(
            (change["classification"] for change in changes),
            key=_CLASSIFICATION_ORDER.__getitem__,
        )
    payload = {
        "format": report_format,
        "classification": classification,
        "change_count": len(changes),
        "changes": changes,
    }
    return {
        **payload,
        "compatibility_diff_id": _sha256_json(payload),
    }


def _require_string_list(
    value: Any,
    *,
    label: str,
    sorted_unique: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise RuntimeEvidenceCompatibilityError(f"{label} must be a list")
    items = tuple(value)
    if any(not isinstance(item, str) or not item for item in items):
        raise RuntimeEvidenceCompatibilityError(
            f"{label} must contain non-empty strings"
        )
    if len(items) != len(set(items)):
        raise RuntimeEvidenceCompatibilityError(f"{label} must not contain duplicates")
    if sorted_unique and items != tuple(sorted(items)):
        raise RuntimeEvidenceCompatibilityError(f"{label} must be sorted")
    return items


def _require_exact_fields(
    value: Mapping[str, Any],
    expected: set[str],
    *,
    label: str,
) -> None:
    if set(value) != expected:
        raise RuntimeEvidenceCompatibilityError(f"{label} has invalid fields")


def _require_non_negative_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeEvidenceCompatibilityError(
            f"{label} must be a non-negative integer"
        )
    return value


def _require_service_graph(
    document: Mapping[str, Any],
    *,
    label: str,
) -> dict[str, Mapping[str, Any]]:
    required = {"format", "service_count", "services", "service_graph_id"}
    optional = {"initialized_service_count", "initialized_services"}
    fields = set(document)
    if not required <= fields or fields - required - optional:
        raise RuntimeEvidenceCompatibilityError(
            f"{label} service graph has invalid fields"
        )
    if document.get("format") != SERVICE_GRAPH_FORMAT:
        raise RuntimeEvidenceCompatibilityError(
            f"unsupported {label} evidence format {document.get('format')!r}"
        )
    services = document.get("services")
    if not isinstance(services, Sequence) or isinstance(
        services,
        (str, bytes, bytearray),
    ):
        raise RuntimeEvidenceCompatibilityError(
            f"{label} service graph services must be a list"
        )

    names: list[str] = []
    service_map: dict[str, Mapping[str, Any]] = {}
    for position, service in enumerate(services):
        if not isinstance(service, Mapping):
            raise RuntimeEvidenceCompatibilityError(
                f"{label} service graph entry {position} must be an object"
            )
        _require_exact_fields(
            service,
            {"name", "origin", "depends_on"},
            label=f"{label} service graph entry {position}",
        )
        name = service.get("name")
        origin = service.get("origin")
        if not isinstance(name, str) or not name:
            raise RuntimeEvidenceCompatibilityError(
                f"{label} service graph entry {position} name is invalid"
            )
        if not isinstance(origin, str) or not origin:
            raise RuntimeEvidenceCompatibilityError(
                f"{label} service graph service {name!r} origin is invalid"
            )
        dependencies = _require_string_list(
            service.get("depends_on"),
            label=f"{label} service graph service {name!r} dependencies",
            sorted_unique=True,
        )
        if name in service_map:
            raise RuntimeEvidenceCompatibilityError(
                f"{label} service graph contains duplicate service {name!r}"
            )
        names.append(name)
        service_map[name] = {
            "name": name,
            "origin": origin,
            "depends_on": list(dependencies),
        }

    if names != sorted(names):
        raise RuntimeEvidenceCompatibilityError(
            f"{label} service graph services must be sorted"
        )
    if _require_non_negative_int(
        document.get("service_count"),
        label=f"{label} service graph service_count",
    ) != len(services):
        raise RuntimeEvidenceCompatibilityError(
            f"{label} service graph service_count does not match services"
        )
    for name, service in service_map.items():
        dependencies = set(service["depends_on"])
        if name in dependencies:
            raise RuntimeEvidenceCompatibilityError(
                f"{label} service graph service {name!r} depends on itself"
            )
        unknown = dependencies - service_map.keys()
        if unknown:
            raise RuntimeEvidenceCompatibilityError(
                f"{label} service graph service {name!r} has unknown dependencies"
            )

    has_initialized_count = "initialized_service_count" in document
    has_initialized_services = "initialized_services" in document
    if has_initialized_count != has_initialized_services:
        raise RuntimeEvidenceCompatibilityError(
            f"{label} service graph initialized state is incomplete"
        )
    if has_initialized_count:
        initialized = _require_string_list(
            document.get("initialized_services"),
            label=f"{label} service graph initialized_services",
            sorted_unique=True,
        )
        if _require_non_negative_int(
            document.get("initialized_service_count"),
            label=f"{label} service graph initialized_service_count",
        ) != len(initialized):
            raise RuntimeEvidenceCompatibilityError(
                f"{label} initialized_service_count does not match"
            )
        if not set(initialized) <= service_map.keys():
            raise RuntimeEvidenceCompatibilityError(
                f"{label} initialized_services contains an unknown service"
            )

    identity_payload = {
        "format": document["format"],
        "service_count": document["service_count"],
        "services": list(services),
    }
    if not _valid_sha256(document.get("service_graph_id")):
        raise RuntimeEvidenceCompatibilityError(
            f"{label} service_graph_id must be a lowercase SHA-256 identity"
        )
    if document["service_graph_id"] != _sha256_json(identity_payload):
        raise RuntimeEvidenceCompatibilityError(
            f"{label} service_graph_id does not match the service graph"
        )
    return service_map


def compare_service_graphs(
    old_document: Mapping[str, Any],
    new_document: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a deterministic comparison of static runtime service topology."""

    old_services = _require_service_graph(old_document, label="old")
    new_services = _require_service_graph(new_document, label="new")
    changes: list[dict[str, Any]] = []
    for name in sorted(old_services.keys() - new_services.keys()):
        changes.append(
            _change(
                f"/services/{name}",
                "service-removed",
                old_services[name],
                None,
            )
        )
    for name in sorted(new_services.keys() - old_services.keys()):
        changes.append(
            _change(
                f"/services/{name}",
                "service-added",
                None,
                new_services[name],
            )
        )
    for name in sorted(old_services.keys() & new_services.keys()):
        old_service = old_services[name]
        new_service = new_services[name]
        if old_service["origin"] != new_service["origin"]:
            changes.append(
                _change(
                    f"/services/{name}/origin",
                    "service-origin-changed",
                    old_service["origin"],
                    new_service["origin"],
                )
            )
        if old_service["depends_on"] != new_service["depends_on"]:
            changes.append(
                _change(
                    f"/services/{name}/depends_on",
                    "service-dependencies-changed",
                    old_service["depends_on"],
                    new_service["depends_on"],
                )
            )
    return _report(SERVICE_GRAPH_COMPATIBILITY_DIFF_FORMAT, changes)


def _require_runtime_identity(
    document: Mapping[str, Any],
    *,
    label: str,
) -> Mapping[str, Any]:
    expected = {
        "format",
        "jacquard",
        "python",
        "mcp",
        "database",
        "compiler",
        "sandbox",
        "configuration",
        "runtime_id",
    }
    _require_exact_fields(document, expected, label=f"{label} runtime identity")
    if document.get("format") != RUNTIME_IDENTITY_FORMAT:
        raise RuntimeEvidenceCompatibilityError(
            f"unsupported {label} evidence format {document.get('format')!r}"
        )
    for field in (
        "jacquard",
        "python",
        "mcp",
        "database",
        "compiler",
        "sandbox",
        "configuration",
    ):
        if not isinstance(document.get(field), Mapping):
            raise RuntimeEvidenceCompatibilityError(
                f"{label} runtime identity {field} must be an object"
            )

    jacquard = document["jacquard"]
    _require_exact_fields(
        jacquard,
        {
            "version",
            "application_id",
            "tool_manifest_id",
            "tool_count",
            "capability_count",
        },
        label=f"{label} runtime identity jacquard",
    )
    for field in ("application_id", "tool_manifest_id"):
        if not _valid_sha256(jacquard.get(field)):
            raise RuntimeEvidenceCompatibilityError(
                f"{label} runtime identity jacquard {field} is invalid"
            )
    for field in ("tool_count", "capability_count"):
        _require_non_negative_int(
            jacquard.get(field),
            label=f"{label} runtime identity jacquard {field}",
        )

    python = document["python"]
    _require_exact_fields(
        python,
        {"implementation", "version", "executable_sha256"},
        label=f"{label} runtime identity python",
    )
    for field in ("implementation", "version"):
        if not isinstance(python.get(field), str) or not python[field]:
            raise RuntimeEvidenceCompatibilityError(
                f"{label} runtime identity python {field} is invalid"
            )
    executable_sha256 = python.get("executable_sha256")
    if executable_sha256 is not None and not _valid_sha256(executable_sha256):
        raise RuntimeEvidenceCompatibilityError(
            f"{label} runtime identity python executable_sha256 is invalid"
        )

    mcp = document["mcp"]
    _require_exact_fields(mcp, {"version"}, label=f"{label} runtime identity mcp")
    if mcp.get("version") is not None and not isinstance(mcp["version"], str):
        raise RuntimeEvidenceCompatibilityError(
            f"{label} runtime identity mcp version is invalid"
        )

    database = document["database"]
    _require_exact_fields(
        database,
        {
            "schema_version",
            "busy_timeout_ms",
            "journal_mode",
            "foreign_keys",
            "location_id",
        },
        label=f"{label} runtime identity database",
    )
    _require_non_negative_int(
        database.get("schema_version"),
        label=f"{label} runtime identity database schema_version",
    )
    _require_non_negative_int(
        database.get("busy_timeout_ms"),
        label=f"{label} runtime identity database busy_timeout_ms",
    )
    if not isinstance(database.get("journal_mode"), str) or not database["journal_mode"]:
        raise RuntimeEvidenceCompatibilityError(
            f"{label} runtime identity database journal_mode is invalid"
        )
    if not isinstance(database.get("foreign_keys"), bool):
        raise RuntimeEvidenceCompatibilityError(
            f"{label} runtime identity database foreign_keys is invalid"
        )
    if not _valid_sha256(database.get("location_id")):
        raise RuntimeEvidenceCompatibilityError(
            f"{label} runtime identity database location_id is invalid"
        )

    for field in ("compiler", "sandbox"):
        component = document[field]
        if not isinstance(component.get("available"), bool):
            raise RuntimeEvidenceCompatibilityError(
                f"{label} runtime identity {field} available is invalid"
            )

    configuration = document["configuration"]
    _require_exact_fields(
        configuration,
        {
            "variables",
            "configured_variables",
            "value_ids",
            "values_redacted",
        },
        label=f"{label} runtime identity configuration",
    )
    variables = _require_string_list(
        configuration.get("variables"),
        label=f"{label} runtime identity configuration variables",
        sorted_unique=True,
    )
    configured = _require_string_list(
        configuration.get("configured_variables"),
        label=f"{label} runtime identity configured_variables",
        sorted_unique=True,
    )
    if not set(configured) <= set(variables):
        raise RuntimeEvidenceCompatibilityError(
            f"{label} configured_variables is not a subset of variables"
        )
    value_ids = configuration.get("value_ids")
    if not isinstance(value_ids, Mapping) or set(value_ids) != set(configured):
        raise RuntimeEvidenceCompatibilityError(
            f"{label} runtime identity value_ids does not match configured_variables"
        )
    if any(not _valid_sha256(value) for value in value_ids.values()):
        raise RuntimeEvidenceCompatibilityError(
            f"{label} runtime identity value_ids contains an invalid identity"
        )
    if configuration.get("values_redacted") is not True:
        raise RuntimeEvidenceCompatibilityError(
            f"{label} runtime identity values must be redacted"
        )

    if not _valid_sha256(document.get("runtime_id")):
        raise RuntimeEvidenceCompatibilityError(
            f"{label} runtime_id must be a lowercase SHA-256 identity"
        )
    payload = {key: document[key] for key in expected if key != "runtime_id"}
    if document["runtime_id"] != _sha256_json(payload):
        raise RuntimeEvidenceCompatibilityError(
            f"{label} runtime_id does not match the runtime evidence"
        )
    return document


def _pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _recursive_changes(
    pointer: str,
    old: Any,
    new: Any,
    changes: list[dict[str, Any]],
) -> None:
    if isinstance(old, Mapping) and isinstance(new, Mapping):
        for key in sorted(old.keys() - new.keys()):
            changes.append(
                _change(
                    f"{pointer}/{_pointer_token(str(key))}",
                    "runtime-field-removed",
                    old[key],
                    None,
                )
            )
        for key in sorted(new.keys() - old.keys()):
            changes.append(
                _change(
                    f"{pointer}/{_pointer_token(str(key))}",
                    "runtime-field-added",
                    None,
                    new[key],
                )
            )
        for key in sorted(old.keys() & new.keys()):
            _recursive_changes(
                f"{pointer}/{_pointer_token(str(key))}",
                old[key],
                new[key],
                changes,
            )
        return
    if old != new:
        changes.append(
            _change(
                pointer,
                "runtime-value-changed",
                old,
                new,
            )
        )


def compare_runtime_identities(
    old_document: Mapping[str, Any],
    new_document: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a deterministic component-level runtime evidence comparison."""

    old = _require_runtime_identity(old_document, label="old")
    new = _require_runtime_identity(new_document, label="new")
    changes: list[dict[str, Any]] = []
    for component in (
        "jacquard",
        "python",
        "mcp",
        "database",
        "compiler",
        "sandbox",
        "configuration",
    ):
        _recursive_changes(
            f"/{component}",
            old[component],
            new[component],
            changes,
        )
    return _report(RUNTIME_IDENTITY_COMPATIBILITY_DIFF_FORMAT, changes)


def compare_runtime_evidence(
    old_document: Mapping[str, Any],
    new_document: Mapping[str, Any],
) -> dict[str, Any]:
    """Dispatch to one strict runtime-evidence comparator."""

    old_format = old_document.get("format")
    new_format = new_document.get("format")
    if old_format == SERVICE_GRAPH_FORMAT:
        if new_format != SERVICE_GRAPH_FORMAT:
            if new_format == RUNTIME_IDENTITY_FORMAT:
                raise RuntimeEvidenceCompatibilityError(
                    "evidence families differ: service graph != runtime identity"
                )
            raise RuntimeEvidenceCompatibilityError(
                f"unsupported new evidence format {new_format!r}"
            )
        return compare_service_graphs(old_document, new_document)
    if old_format == RUNTIME_IDENTITY_FORMAT:
        if new_format != RUNTIME_IDENTITY_FORMAT:
            if new_format == SERVICE_GRAPH_FORMAT:
                raise RuntimeEvidenceCompatibilityError(
                    "evidence families differ: runtime identity != service graph"
                )
            raise RuntimeEvidenceCompatibilityError(
                f"unsupported new evidence format {new_format!r}"
            )
        return compare_runtime_identities(old_document, new_document)
    raise RuntimeEvidenceCompatibilityError(
        f"unsupported old evidence format {old_format!r}"
    )


__all__ = [
    "RUNTIME_IDENTITY_COMPATIBILITY_DIFF_FORMAT",
    "RUNTIME_IDENTITY_FORMAT",
    "SERVICE_GRAPH_COMPATIBILITY_DIFF_FORMAT",
    "SERVICE_GRAPH_FORMAT",
    "RuntimeEvidenceCompatibilityError",
    "compare_runtime_evidence",
    "compare_runtime_identities",
    "compare_service_graphs",
]
