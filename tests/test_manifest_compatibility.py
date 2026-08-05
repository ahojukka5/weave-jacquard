from __future__ import annotations

import pytest

from weave_frontend.application import build_tool_manifest
from weave_frontend.manifest_compatibility import (
    APPLICATION_COMPATIBILITY_DIFF_FORMAT,
    COMPATIBILITY_DIFF_FORMAT,
    ManifestCompatibilityError,
    compare_application_manifests,
    compare_manifests,
    compare_tool_manifests,
)


def _manifest(*tools: dict[str, object]) -> dict[str, object]:
    return {
        "format": "weave-jacquard-tool-manifest-v1",
        "tools": list(tools),
    }


def _tool(
    name: str,
    *,
    description: str = "Example tool",
    properties: dict[str, object] | None = None,
    required: list[str] | None = None,
) -> dict[str, object]:
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties or {},
            "required": required or [],
            "additionalProperties": False,
        },
        "output_schema": None,
        "annotations": None,
        "metadata": None,
    }


def _v2_contract(
    name: str,
    *,
    description: str | None = None,
    properties: dict[str, object] | None = None,
    required: list[str] | None = None,
    output_schema: dict[str, object] | None = None,
    meta: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "name": name,
        "title": None,
        "description": description or f"Tool {name}",
        "input_schema": {
            "type": "object",
            "properties": properties or {},
            "required": required or [],
            "additionalProperties": False,
        },
        "output_schema": output_schema,
        "annotations": None,
        "icons": None,
        "meta": meta,
    }


def _application_manifest(
    *,
    capabilities: list[dict[str, object]] | None = None,
    tool_manifest_id: str = "tool-a",
    tool_count: int = 1,
    configuration_variables: list[str] | None = None,
) -> dict[str, object]:
    return {
        "format": "weave-jacquard-application-v2",
        "capabilities": capabilities
        or [
            {
                "name": "base",
                "module": "example.base",
                "depends_on": [],
            }
        ],
        "tool_manifest_id": tool_manifest_id,
        "tool_count": tool_count,
        "configuration_variables": configuration_variables or ["WEAVE_DB"],
        "application_id": "application-id",
    }


def test_identical_manifests_produce_empty_deterministic_diff() -> None:
    manifest = _manifest(_tool("alpha"), _tool("beta"))

    first = compare_tool_manifests(manifest, manifest)
    second = compare_tool_manifests(manifest, manifest)

    assert first == second
    assert first["format"] == COMPATIBILITY_DIFF_FORMAT
    assert first["classification"] == "identity-only"
    assert first["change_count"] == 0
    assert first["changes"] == []


def test_tool_removal_is_breaking() -> None:
    report = compare_tool_manifests(
        _manifest(_tool("alpha"), _tool("beta")),
        _manifest(_tool("alpha")),
    )

    assert report["classification"] == "breaking"
    assert report["changes"] == [
        {
            "pointer": "/tools/beta",
            "classification": "breaking",
            "kind": "tool-removed",
            "old": _tool("beta"),
            "new": None,
        }
    ]


def test_optional_parameter_addition_is_additive() -> None:
    report = compare_tool_manifests(
        _manifest(_tool("alpha")),
        _manifest(
            _tool(
                "alpha",
                properties={"limit": {"type": "integer", "default": 10}},
            )
        ),
    )

    assert report["classification"] == "additive-compatible"
    assert report["changes"][0]["kind"] == "parameter-added"
    assert report["changes"][0]["pointer"] == ("/tools/alpha/parameters/properties/limit")


def test_required_parameter_addition_is_breaking() -> None:
    report = compare_tool_manifests(
        _manifest(_tool("alpha")),
        _manifest(
            _tool(
                "alpha",
                properties={"project_id": {"type": "string"}},
                required=["project_id"],
            )
        ),
    )

    assert report["classification"] == "breaking"
    assert {change["kind"] for change in report["changes"]} == {
        "parameter-added",
        "required-parameter-added",
    }


def test_description_change_is_documentation_only() -> None:
    report = compare_tool_manifests(
        _manifest(_tool("alpha", description="Old description")),
        _manifest(_tool("alpha", description="New description")),
    )

    assert report["classification"] == "documentation-only"
    assert report["changes"] == [
        {
            "pointer": "/tools/alpha/description",
            "classification": "documentation-only",
            "kind": "description-changed",
            "old": "Old description",
            "new": "New description",
        }
    ]


def test_registry_order_does_not_change_report() -> None:
    old = _manifest(_tool("beta"), _tool("alpha"))
    new = _manifest(_tool("gamma"), _tool("alpha"), _tool("beta"))

    reordered_old = _manifest(_tool("alpha"), _tool("beta"))
    reordered_new = _manifest(_tool("beta"), _tool("gamma"), _tool("alpha"))

    assert compare_tool_manifests(old, new) == compare_tool_manifests(
        reordered_old,
        reordered_new,
    )


def test_current_tool_manifest_format_uses_input_schema_and_meta() -> None:
    old = build_tool_manifest(
        [_v2_contract("alpha")],
        required_tools=(),
    )
    new = build_tool_manifest(
        [
            _v2_contract(
                "alpha",
                properties={"limit": {"type": "integer"}},
                meta={"stability": "experimental"},
            )
        ],
        required_tools=(),
    )

    report = compare_tool_manifests(old, new)

    assert report["classification"] == "behavior-review-required"
    assert {change["kind"] for change in report["changes"]} == {
        "parameter-added",
        "meta-changed",
    }
    assert report["changes"][0]["pointer"].startswith("/tools/alpha/input_schema/")


def test_current_tool_manifest_shape_is_checked() -> None:
    manifest = build_tool_manifest([_v2_contract("alpha")], required_tools=())
    manifest["tool_count"] = 2

    with pytest.raises(ManifestCompatibilityError, match="tool_count"):
        compare_tool_manifests(manifest, manifest)


def test_application_manifest_configuration_addition_is_additive() -> None:
    old = _application_manifest(configuration_variables=["WEAVE_DB"])
    new = _application_manifest(configuration_variables=["WEAVE_DB", "WEAVE_ROOT"])

    report = compare_application_manifests(old, new)

    assert report["format"] == APPLICATION_COMPATIBILITY_DIFF_FORMAT
    assert report["classification"] == "additive-compatible"
    assert report["changes"] == [
        {
            "pointer": "/configuration_variables/WEAVE_ROOT",
            "classification": "additive-compatible",
            "kind": "configuration-variable-added",
            "old": False,
            "new": True,
        }
    ]


def test_application_manifest_capability_removal_is_breaking() -> None:
    old = _application_manifest(
        capabilities=[
            {"name": "base", "module": "example.base", "depends_on": []},
            {
                "name": "feature",
                "module": "example.feature",
                "depends_on": ["base"],
            },
        ]
    )
    new = _application_manifest()

    report = compare_application_manifests(old, new)

    assert report["classification"] == "breaking"
    assert report["changes"][0]["kind"] == "capability-removed"


def test_application_manifest_order_and_tool_identity_are_explicit() -> None:
    old = _application_manifest(
        capabilities=[
            {"name": "alpha", "module": "example.alpha", "depends_on": []},
            {"name": "beta", "module": "example.beta", "depends_on": []},
        ],
        tool_manifest_id="tool-a",
    )
    new = _application_manifest(
        capabilities=[
            {"name": "beta", "module": "example.beta", "depends_on": []},
            {"name": "alpha", "module": "example.alpha", "depends_on": []},
        ],
        tool_manifest_id="tool-b",
    )

    report = compare_manifests(old, new)

    assert report["classification"] == "behavior-review-required"
    assert {change["kind"] for change in report["changes"]} == {
        "capability-order-changed",
        "tool-manifest-id-changed",
    }


def test_manifest_families_cannot_be_compared() -> None:
    with pytest.raises(ManifestCompatibilityError, match="manifest families differ"):
        compare_manifests(_manifest(_tool("alpha")), _application_manifest())


@pytest.mark.parametrize(
    "manifest",
    [
        {"format": "future-format", "tools": []},
        {"format": "weave-jacquard-tool-manifest-v1", "tools": "invalid"},
        _manifest(_tool("duplicate"), _tool("duplicate")),
    ],
)
def test_invalid_or_unknown_manifests_fail_closed(
    manifest: dict[str, object],
) -> None:
    with pytest.raises(ManifestCompatibilityError):
        compare_tool_manifests(manifest, _manifest())
