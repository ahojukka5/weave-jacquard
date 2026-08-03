"""Deterministic semantic compatibility diffing for retained manifests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

COMPATIBILITY_DIFF_FORMAT = "weave-jacquard-compatibility-diff-v1"
APPLICATION_COMPATIBILITY_DIFF_FORMAT = (
    "weave-jacquard-application-compatibility-diff-v1"
)
SUPPORTED_TOOL_MANIFEST_FORMATS = frozenset(
    {
        "weave-jacquard-tool-manifest-v1",
        "weave-jacquard-tool-manifest-v2",
    }
)
SUPPORTED_APPLICATION_MANIFEST_FORMATS = frozenset(
    {"weave-jacquard-application-v2"}
)
_CLASSIFICATION_ORDER = {
    "identity-only": 0,
    "documentation-only": 1,
    "additive-compatible": 2,
    "behavior-review-required": 3,
    "breaking": 4,
}


class ManifestCompatibilityError(ValueError):
    """Raised when a manifest cannot be compared safely."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _fragment(value: Any) -> Any:
    encoded = _canonical_json(value)
    if len(encoded) <= 512:
        return value
    return {
        "sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        "truncated": True,
    }


def _require_string_list(
    value: Any,
    *,
    label: str,
    sorted_unique: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ManifestCompatibilityError(f"{label} must be a list")
    items = tuple(value)
    if any(not isinstance(item, str) or not item for item in items):
        raise ManifestCompatibilityError(f"{label} must contain non-empty strings")
    if len(items) != len(set(items)):
        raise ManifestCompatibilityError(f"{label} must not contain duplicates")
    if sorted_unique and items != tuple(sorted(items)):
        raise ManifestCompatibilityError(f"{label} must be sorted")
    return items


def _require_tool_manifest(manifest: Mapping[str, Any], label: str) -> str:
    manifest_format = manifest.get("format")
    if manifest_format not in SUPPORTED_TOOL_MANIFEST_FORMATS:
        raise ManifestCompatibilityError(
            f"unsupported {label} manifest format {manifest_format!r}"
        )
    tools = manifest.get("tools")
    if not isinstance(tools, Sequence) or isinstance(tools, (str, bytes, bytearray)):
        raise ManifestCompatibilityError(f"{label} manifest tools must be a list")
    names: list[str] = []
    schema_field = "input_schema" if manifest_format.endswith("-v2") else "parameters"
    for index, tool in enumerate(tools):
        if not isinstance(tool, Mapping):
            raise ManifestCompatibilityError(
                f"{label} manifest tool at index {index} must be an object"
            )
        name = tool.get("name")
        if not isinstance(name, str) or not name:
            raise ManifestCompatibilityError(
                f"{label} manifest tool at index {index} has no valid name"
            )
        if name in names:
            raise ManifestCompatibilityError(
                f"{label} manifest contains duplicate tool {name!r}"
            )
        names.append(name)
        if not isinstance(tool.get(schema_field, {}), Mapping):
            raise ManifestCompatibilityError(
                f"tool {name!r} {schema_field} must be an object"
            )

    if manifest_format.endswith("-v2"):
        tool_count = manifest.get("tool_count")
        if (
            isinstance(tool_count, bool)
            or not isinstance(tool_count, int)
            or tool_count != len(tools)
        ):
            raise ManifestCompatibilityError(
                f"{label} manifest tool_count does not match tools"
            )
        tool_names = _require_string_list(
            manifest.get("tool_names"),
            label=f"{label} manifest tool_names",
            sorted_unique=True,
        )
        if tool_names != tuple(sorted(names)):
            raise ManifestCompatibilityError(
                f"{label} manifest tool_names does not match tools"
            )
        if not isinstance(manifest.get("tool_manifest_id"), str):
            raise ManifestCompatibilityError(
                f"{label} manifest tool_manifest_id must be a string"
            )
    return manifest_format


def _require_application_manifest(manifest: Mapping[str, Any], label: str) -> str:
    manifest_format = manifest.get("format")
    if manifest_format not in SUPPORTED_APPLICATION_MANIFEST_FORMATS:
        raise ManifestCompatibilityError(
            f"unsupported {label} manifest format {manifest_format!r}"
        )
    capabilities = manifest.get("capabilities")
    if not isinstance(capabilities, Sequence) or isinstance(
        capabilities, (str, bytes, bytearray)
    ):
        raise ManifestCompatibilityError(f"{label} manifest capabilities must be a list")
    seen: set[str] = set()
    for index, capability in enumerate(capabilities):
        if not isinstance(capability, Mapping):
            raise ManifestCompatibilityError(
                f"{label} manifest capability at index {index} must be an object"
            )
        name = capability.get("name")
        module = capability.get("module")
        if not isinstance(name, str) or not name:
            raise ManifestCompatibilityError(
                f"{label} manifest capability at index {index} has no valid name"
            )
        if not isinstance(module, str) or not module:
            raise ManifestCompatibilityError(
                f"{label} manifest capability {name!r} has no valid module"
            )
        if name in seen:
            raise ManifestCompatibilityError(
                f"{label} manifest contains duplicate capability {name!r}"
            )
        _require_string_list(
            capability.get("depends_on"),
            label=f"{label} manifest capability {name!r} dependencies",
        )
        seen.add(name)
    tool_count = manifest.get("tool_count")
    if isinstance(tool_count, bool) or not isinstance(tool_count, int) or tool_count < 0:
        raise ManifestCompatibilityError(
            f"{label} manifest tool_count must be a non-negative integer"
        )
    if not isinstance(manifest.get("tool_manifest_id"), str):
        raise ManifestCompatibilityError(
            f"{label} manifest tool_manifest_id must be a string"
        )
    _require_string_list(
        manifest.get("configuration_variables"),
        label=f"{label} manifest configuration_variables",
        sorted_unique=True,
    )
    if not isinstance(manifest.get("application_id"), str):
        raise ManifestCompatibilityError(
            f"{label} manifest application_id must be a string"
        )
    return manifest_format


def _tool_map(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {tool["name"]: tool for tool in manifest["tools"]}


def _change(
    pointer: str,
    classification: str,
    kind: str,
    old: Any,
    new: Any,
) -> dict[str, Any]:
    return {
        "pointer": pointer,
        "classification": classification,
        "kind": kind,
        "old": _fragment(old),
        "new": _fragment(new),
    }


def _schema_changes(
    tool_name: str,
    schema_field: str,
    old_schema: Mapping[str, Any],
    new_schema: Mapping[str, Any],
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    base = f"/tools/{tool_name}/{schema_field}"
    old_required = set(
        _require_string_list(
            old_schema.get("required", []),
            label=f"tool {tool_name!r} required parameters",
        )
    )
    new_required = set(
        _require_string_list(
            new_schema.get("required", []),
            label=f"tool {tool_name!r} required parameters",
        )
    )
    for name in sorted(old_required - new_required):
        changes.append(
            _change(
                f"{base}/required/{name}",
                "additive-compatible",
                "required-parameter-relaxed",
                True,
                False,
            )
        )
    for name in sorted(new_required - old_required):
        changes.append(
            _change(
                f"{base}/required/{name}",
                "breaking",
                "required-parameter-added",
                False,
                True,
            )
        )

    old_properties = old_schema.get("properties", {})
    new_properties = new_schema.get("properties", {})
    if not isinstance(old_properties, Mapping) or not isinstance(
        new_properties, Mapping
    ):
        if old_schema != new_schema:
            changes.append(
                _change(
                    base,
                    "behavior-review-required",
                    "parameter-schema-changed",
                    old_schema,
                    new_schema,
                )
            )
        return changes

    for name in sorted(old_properties.keys() - new_properties.keys()):
        changes.append(
            _change(
                f"{base}/properties/{name}",
                "breaking",
                "parameter-removed",
                old_properties[name],
                None,
            )
        )
    for name in sorted(new_properties.keys() - old_properties.keys()):
        classification = "breaking" if name in new_required else "additive-compatible"
        changes.append(
            _change(
                f"{base}/properties/{name}",
                classification,
                "parameter-added",
                None,
                new_properties[name],
            )
        )
    for name in sorted(old_properties.keys() & new_properties.keys()):
        if old_properties[name] != new_properties[name]:
            changes.append(
                _change(
                    f"{base}/properties/{name}",
                    "behavior-review-required",
                    "parameter-schema-changed",
                    old_properties[name],
                    new_properties[name],
                )
            )
    return changes


def _report(
    report_format: str,
    changes: list[dict[str, Any]],
) -> dict[str, Any]:
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
        "compatibility_diff_id": hashlib.sha256(
            _canonical_json(payload).encode("utf-8")
        ).hexdigest(),
    }


def compare_tool_manifests(
    old_manifest: Mapping[str, Any],
    new_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a deterministic conservative tool-manifest compatibility report."""

    old_format = _require_tool_manifest(old_manifest, "old")
    new_format = _require_tool_manifest(new_manifest, "new")
    if old_format != new_format:
        raise ManifestCompatibilityError(
            f"tool manifest formats differ: {old_format!r} != {new_format!r}"
        )
    schema_field = "input_schema" if old_format.endswith("-v2") else "parameters"
    behavior_fields = ("output_schema", "annotations", "icons", "meta")
    if old_format.endswith("-v1"):
        behavior_fields = ("output_schema", "annotations", "metadata")

    old_tools = _tool_map(old_manifest)
    new_tools = _tool_map(new_manifest)
    changes: list[dict[str, Any]] = []
    for name in sorted(old_tools.keys() - new_tools.keys()):
        changes.append(
            _change(
                f"/tools/{name}",
                "breaking",
                "tool-removed",
                old_tools[name],
                None,
            )
        )
    for name in sorted(new_tools.keys() - old_tools.keys()):
        changes.append(
            _change(
                f"/tools/{name}",
                "additive-compatible",
                "tool-added",
                None,
                new_tools[name],
            )
        )
    for name in sorted(old_tools.keys() & new_tools.keys()):
        old_tool = old_tools[name]
        new_tool = new_tools[name]
        changes.extend(
            _schema_changes(
                name,
                schema_field,
                old_tool.get(schema_field, {}),
                new_tool.get(schema_field, {}),
            )
        )
        for field in behavior_fields:
            if old_tool.get(field) != new_tool.get(field):
                changes.append(
                    _change(
                        f"/tools/{name}/{field}",
                        "behavior-review-required",
                        f"{field.replace('_', '-')}-changed",
                        old_tool.get(field),
                        new_tool.get(field),
                    )
                )
        for field in ("description", "title"):
            if old_tool.get(field) != new_tool.get(field):
                changes.append(
                    _change(
                        f"/tools/{name}/{field}",
                        "documentation-only",
                        f"{field}-changed",
                        old_tool.get(field),
                        new_tool.get(field),
                    )
                )
    return _report(COMPATIBILITY_DIFF_FORMAT, changes)


def _capability_map(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        capability["name"]: capability
        for capability in manifest["capabilities"]
    }


def compare_application_manifests(
    old_manifest: Mapping[str, Any],
    new_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a deterministic conservative application compatibility report."""

    old_format = _require_application_manifest(old_manifest, "old")
    new_format = _require_application_manifest(new_manifest, "new")
    if old_format != new_format:
        raise ManifestCompatibilityError(
            f"application manifest formats differ: {old_format!r} != {new_format!r}"
        )
    changes: list[dict[str, Any]] = []
    old_capabilities = _capability_map(old_manifest)
    new_capabilities = _capability_map(new_manifest)
    for name in sorted(old_capabilities.keys() - new_capabilities.keys()):
        changes.append(
            _change(
                f"/capabilities/{name}",
                "breaking",
                "capability-removed",
                old_capabilities[name],
                None,
            )
        )
    for name in sorted(new_capabilities.keys() - old_capabilities.keys()):
        changes.append(
            _change(
                f"/capabilities/{name}",
                "additive-compatible",
                "capability-added",
                None,
                new_capabilities[name],
            )
        )
    for name in sorted(old_capabilities.keys() & new_capabilities.keys()):
        if old_capabilities[name] != new_capabilities[name]:
            changes.append(
                _change(
                    f"/capabilities/{name}",
                    "behavior-review-required",
                    "capability-contract-changed",
                    old_capabilities[name],
                    new_capabilities[name],
                )
            )

    old_order = [item["name"] for item in old_manifest["capabilities"]]
    new_order = [item["name"] for item in new_manifest["capabilities"]]
    if set(old_order) == set(new_order) and old_order != new_order:
        changes.append(
            _change(
                "/capabilities/order",
                "behavior-review-required",
                "capability-order-changed",
                old_order,
                new_order,
            )
        )

    old_variables = set(old_manifest["configuration_variables"])
    new_variables = set(new_manifest["configuration_variables"])
    for name in sorted(old_variables - new_variables):
        changes.append(
            _change(
                f"/configuration_variables/{name}",
                "breaking",
                "configuration-variable-removed",
                True,
                False,
            )
        )
    for name in sorted(new_variables - old_variables):
        changes.append(
            _change(
                f"/configuration_variables/{name}",
                "additive-compatible",
                "configuration-variable-added",
                False,
                True,
            )
        )
    for field, kind in (
        ("tool_manifest_id", "tool-manifest-id-changed"),
        ("tool_count", "tool-count-changed"),
    ):
        if old_manifest[field] != new_manifest[field]:
            changes.append(
                _change(
                    f"/{field}",
                    "behavior-review-required",
                    kind,
                    old_manifest[field],
                    new_manifest[field],
                )
            )
    return _report(APPLICATION_COMPATIBILITY_DIFF_FORMAT, changes)


def compare_manifests(
    old_manifest: Mapping[str, Any],
    new_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Dispatch to the strict comparator for one supported manifest family."""

    old_format = old_manifest.get("format")
    new_format = new_manifest.get("format")
    if old_format in SUPPORTED_TOOL_MANIFEST_FORMATS:
        if new_format not in SUPPORTED_TOOL_MANIFEST_FORMATS:
            if new_format in SUPPORTED_APPLICATION_MANIFEST_FORMATS:
                raise ManifestCompatibilityError(
                    "manifest families differ: tool manifest != application manifest"
                )
            raise ManifestCompatibilityError(
                f"unsupported new manifest format {new_format!r}"
            )
        return compare_tool_manifests(old_manifest, new_manifest)
    if old_format in SUPPORTED_APPLICATION_MANIFEST_FORMATS:
        if new_format not in SUPPORTED_APPLICATION_MANIFEST_FORMATS:
            if new_format in SUPPORTED_TOOL_MANIFEST_FORMATS:
                raise ManifestCompatibilityError(
                    "manifest families differ: application manifest != tool manifest"
                )
            raise ManifestCompatibilityError(
                f"unsupported new manifest format {new_format!r}"
            )
        return compare_application_manifests(old_manifest, new_manifest)
    raise ManifestCompatibilityError(
        f"unsupported old manifest format {old_format!r}"
    )


__all__ = [
    "APPLICATION_COMPATIBILITY_DIFF_FORMAT",
    "COMPATIBILITY_DIFF_FORMAT",
    "ManifestCompatibilityError",
    "compare_application_manifests",
    "compare_manifests",
    "compare_tool_manifests",
]
