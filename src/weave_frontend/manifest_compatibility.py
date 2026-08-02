"""Deterministic semantic compatibility diffing for retained manifests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

COMPATIBILITY_DIFF_FORMAT = "weave-jacquard-compatibility-diff-v1"
SUPPORTED_TOOL_MANIFEST_FORMATS = frozenset({"weave-jacquard-tool-manifest-v1"})
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
    )


def _fragment(value: Any) -> Any:
    encoded = _canonical_json(value)
    if len(encoded) <= 512:
        return value
    return {
        "sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        "truncated": True,
    }


def _require_manifest(manifest: Mapping[str, Any], label: str) -> None:
    manifest_format = manifest.get("format")
    if manifest_format not in SUPPORTED_TOOL_MANIFEST_FORMATS:
        raise ManifestCompatibilityError(
            f"unsupported {label} manifest format {manifest_format!r}"
        )
    tools = manifest.get("tools")
    if not isinstance(tools, Sequence) or isinstance(tools, (str, bytes)):
        raise ManifestCompatibilityError(f"{label} manifest tools must be a list")
    names: set[str] = set()
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
        names.add(name)


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
    old_schema: Mapping[str, Any],
    new_schema: Mapping[str, Any],
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    base = f"/tools/{tool_name}/parameters"
    old_required = set(old_schema.get("required", ()))
    new_required = set(new_schema.get("required", ()))
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


def compare_tool_manifests(
    old_manifest: Mapping[str, Any],
    new_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a deterministic conservative compatibility report."""

    _require_manifest(old_manifest, "old")
    _require_manifest(new_manifest, "new")
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
        old_parameters = old_tool.get("parameters", {})
        new_parameters = new_tool.get("parameters", {})
        if not isinstance(old_parameters, Mapping) or not isinstance(
            new_parameters, Mapping
        ):
            raise ManifestCompatibilityError(
                f"tool {name!r} parameters must be objects"
            )
        changes.extend(_schema_changes(name, old_parameters, new_parameters))

        for field in ("output_schema", "annotations", "metadata"):
            old_value = old_tool.get(field)
            new_value = new_tool.get(field)
            if old_value != new_value:
                changes.append(
                    _change(
                        f"/tools/{name}/{field}",
                        "behavior-review-required",
                        f"{field.replace('_', '-')}-changed",
                        old_value,
                        new_value,
                    )
                )
        for field in ("description", "title"):
            old_value = old_tool.get(field)
            new_value = new_tool.get(field)
            if old_value != new_value:
                changes.append(
                    _change(
                        f"/tools/{name}/{field}",
                        "documentation-only",
                        f"{field}-changed",
                        old_value,
                        new_value,
                    )
                )

    changes.sort(key=lambda item: (item["pointer"], item["kind"]))
    classification = "identity-only"
    if changes:
        classification = max(
            (change["classification"] for change in changes),
            key=_CLASSIFICATION_ORDER.__getitem__,
        )
    payload = {
        "format": COMPATIBILITY_DIFF_FORMAT,
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


__all__ = [
    "COMPATIBILITY_DIFF_FORMAT",
    "ManifestCompatibilityError",
    "compare_tool_manifests",
]
