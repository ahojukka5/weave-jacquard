from __future__ import annotations

from copy import deepcopy

import pytest

from weave_frontend.manifest_compatibility import (
    ManifestCompatibilityError,
    compare_tool_manifests,
)


def _tool(
    *,
    name: str = "example",
    schema: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "name": name,
        "description": "Example tool",
        "parameters": schema
        or {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        "output_schema": None,
        "annotations": None,
        "metadata": None,
    }


def _manifest(tool: dict[str, object]) -> dict[str, object]:
    return {
        "format": "weave-jacquard-tool-manifest-v1",
        "tools": [tool],
    }


def _parameter_schema(parameter: dict[str, object]) -> dict[str, object]:
    return {
        "type": "object",
        "properties": {"mode": parameter},
        "required": [],
        "additionalProperties": False,
    }


@pytest.mark.parametrize(
    ("old_parameter", "new_parameter", "kind", "old_value", "new_value"),
    [
        (
            {"type": "integer"},
            {"type": "integer", "default": 4},
            "parameter-default-added",
            None,
            4,
        ),
        (
            {"type": "integer", "default": 4},
            {"type": "integer"},
            "parameter-default-removed",
            4,
            None,
        ),
        (
            {"type": "integer", "default": 4},
            {"type": "integer", "default": 8},
            "parameter-default-changed",
            4,
            8,
        ),
    ],
)
def test_default_changes_have_explicit_review_classification(
    old_parameter: dict[str, object],
    new_parameter: dict[str, object],
    kind: str,
    old_value: object,
    new_value: object,
) -> None:
    report = compare_tool_manifests(
        _manifest(_tool(schema=_parameter_schema(old_parameter))),
        _manifest(_tool(schema=_parameter_schema(new_parameter))),
    )

    assert report["classification"] == "behavior-review-required"
    assert report["changes"] == [
        {
            "pointer": "/tools/example/parameters/properties/mode/default",
            "classification": "behavior-review-required",
            "kind": kind,
            "old": old_value,
            "new": new_value,
        }
    ]


@pytest.mark.parametrize(
    ("old_enum", "new_enum", "classification", "kind"),
    [
        (
            ["alpha", "beta"],
            ["gamma", "alpha", "beta"],
            "additive-compatible",
            "parameter-enum-expanded",
        ),
        (
            ["alpha", "beta"],
            ["alpha"],
            "breaking",
            "parameter-enum-narrowed",
        ),
        (
            ["alpha", "beta"],
            ["beta", "gamma"],
            "breaking",
            "parameter-enum-changed",
        ),
    ],
)
def test_enum_set_changes_have_conservative_explicit_classification(
    old_enum: list[str],
    new_enum: list[str],
    classification: str,
    kind: str,
) -> None:
    report = compare_tool_manifests(
        _manifest(
            _tool(
                schema=_parameter_schema(
                    {"type": "string", "enum": old_enum}
                )
            )
        ),
        _manifest(
            _tool(
                schema=_parameter_schema(
                    {"type": "string", "enum": new_enum}
                )
            )
        ),
    )

    assert report["classification"] == classification
    assert report["changes"] == [
        {
            "pointer": "/tools/example/parameters/properties/mode/enum",
            "classification": classification,
            "kind": kind,
            "old": sorted(old_enum),
            "new": sorted(new_enum),
        }
    ]


def test_adding_and_removing_enum_constraints_are_distinguished() -> None:
    unconstrained = _manifest(
        _tool(schema=_parameter_schema({"type": "string"}))
    )
    constrained = _manifest(
        _tool(
            schema=_parameter_schema(
                {"type": "string", "enum": ["alpha", "beta"]}
            )
        )
    )

    added = compare_tool_manifests(unconstrained, constrained)
    removed = compare_tool_manifests(constrained, unconstrained)

    assert added["classification"] == "breaking"
    assert added["changes"][0]["kind"] == "parameter-enum-constrained"
    assert removed["classification"] == "additive-compatible"
    assert removed["changes"][0]["kind"] == "parameter-enum-unconstrained"


def test_enum_order_does_not_create_a_semantic_change() -> None:
    old = _manifest(
        _tool(
            schema=_parameter_schema(
                {"type": "string", "enum": ["alpha", "beta"]}
            )
        )
    )
    new = _manifest(
        _tool(
            schema=_parameter_schema(
                {"type": "string", "enum": ["beta", "alpha"]}
            )
        )
    )

    report = compare_tool_manifests(old, new)

    assert report["classification"] == "identity-only"
    assert report["change_count"] == 0


def test_nested_defaults_and_enums_use_exact_json_pointers() -> None:
    old_schema = _parameter_schema(
        {
            "type": "object",
            "properties": {
                "choice/value~raw": {
                    "type": "string",
                    "enum": ["alpha", "beta"],
                    "default": "alpha",
                }
            },
        }
    )
    new_schema = deepcopy(old_schema)
    nested = new_schema["properties"]["mode"]["properties"]["choice/value~raw"]
    nested["enum"] = ["alpha"]
    nested["default"] = "beta"

    report = compare_tool_manifests(
        _manifest(_tool(name="tool/name~raw", schema=old_schema)),
        _manifest(_tool(name="tool/name~raw", schema=new_schema)),
    )

    assert report["classification"] == "breaking"
    assert [change["pointer"] for change in report["changes"]] == [
        (
            "/tools/tool~1name~0raw/parameters/properties/mode/properties/"
            "choice~1value~0raw/default"
        ),
        (
            "/tools/tool~1name~0raw/parameters/properties/mode/properties/"
            "choice~1value~0raw/enum"
        ),
    ]
    assert [change["kind"] for change in report["changes"]] == [
        "parameter-default-changed",
        "parameter-enum-narrowed",
    ]


def test_duplicate_enum_values_fail_closed() -> None:
    invalid = _manifest(
        _tool(
            schema=_parameter_schema(
                {"type": "string", "enum": ["alpha", "alpha"]}
            )
        )
    )
    valid = _manifest(
        _tool(
            schema=_parameter_schema(
                {"type": "string", "enum": ["alpha"]}
            )
        )
    )

    with pytest.raises(ManifestCompatibilityError, match="duplicates"):
        compare_tool_manifests(invalid, valid)
