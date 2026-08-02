from __future__ import annotations

import pytest

from weave_frontend.manifest_compatibility import (
    COMPATIBILITY_DIFF_FORMAT,
    ManifestCompatibilityError,
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
    assert report["changes"][0]["pointer"] == (
        "/tools/alpha/parameters/properties/limit"
    )


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
