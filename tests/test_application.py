from __future__ import annotations

from dataclasses import dataclass, field
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from weave_frontend.application import (
    APPLICATION_MANIFEST_FORMAT,
    PUBLIC_CONFIGURATION_VARIABLES,
    TOOL_MANIFEST_FORMAT,
    ApplicationCompositionError,
    JacquardApp,
    build_tool_manifest,
    registered_tool_contracts,
    registered_tool_names,
)
from weave_frontend.mcp_capabilities import Capability, capability_manifest


@dataclass
class _LowLevelServer:
    instructions: str = "legacy"


@dataclass
class _FakeFnMetadata:
    output_schema: dict[str, Any] | None = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {"result": {"type": "object"}},
            "required": ["result"],
        }
    )


@dataclass
class _FakeTool:
    name: str
    description: str = "Test tool"
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }
    )
    title: str | None = None
    annotations: Any = None
    icons: Any = None
    meta: Any = None
    fn_metadata: _FakeFnMetadata = field(default_factory=_FakeFnMetadata)


def _tool(name: str, **overrides: Any) -> _FakeTool:
    values = {
        "name": name,
        "description": f"Tool {name}",
        **overrides,
    }
    return _FakeTool(**values)


def _contract(
    name: str,
    *,
    description: str | None = None,
    input_type: str = "string",
    output_type: str = "object",
) -> dict[str, Any]:
    return {
        "name": name,
        "title": None,
        "description": description or f"Tool {name}",
        "input_schema": {
            "type": "object",
            "properties": {"value": {"type": input_type}},
            "required": ["value"],
        },
        "output_schema": {
            "type": "object",
            "properties": {"result": {"type": output_type}},
            "required": ["result"],
        },
        "annotations": None,
        "icons": None,
        "meta": None,
    }


class _FakeFastMCP:
    def __init__(self, tools: dict[str, _FakeTool] | None = None) -> None:
        self._mcp_server = _LowLevelServer()
        self.tools = dict(tools or {})
        self.removed: list[str] = []
        self.added: list[str] = []

    def remove_tool(self, name: str) -> None:
        self.removed.append(name)
        del self.tools[name]

    def add_tool(
        self,
        function: Any,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        tool_name = name or function.__name__
        self.tools[tool_name] = _tool(
            tool_name,
            description=description or function.__doc__ or "",
        )
        self.added.append(tool_name)


def _loader(name: str) -> ModuleType:
    if name == "weave_frontend.mcp_revert_guidance":
        return SimpleNamespace(  # type: ignore[return-value]
            INSTRUCTIONS="composed instructions",
            weave_help=lambda topic="workflow": {"ok": True, "topic": topic},
        )
    return ModuleType(name)


def test_application_composes_capabilities_and_tools_deterministically() -> None:
    capabilities = (
        Capability("base", "example.base"),
        Capability("feature", "example.feature", ("base",)),
    )
    server = _FakeFastMCP(
        {
            name: _tool(name)
            for name in (
                "weave_help",
                "project_initialize",
                "program_validate",
                "branch_merge",
                "zeta",
                "alpha",
            )
        }
    )

    app = JacquardApp.compose(
        server,
        capabilities=capabilities,
        module_loader=_loader,
    )

    assert app.server is server
    assert app.capability_manifest == capability_manifest(capabilities)
    assert app.tool_manifest["format"] == TOOL_MANIFEST_FORMAT
    assert app.tool_manifest["tool_names"] == sorted(server.tools)
    assert [tool["name"] for tool in app.tool_manifest["tools"]] == sorted(server.tools)
    assert app.tool_manifest["tool_count"] == len(server.tools)
    assert len(app.tool_manifest["tool_manifest_id"]) == 64
    assert all(len(tool["tool_contract_id"]) == 64 for tool in app.tool_manifest["tools"])
    assert app.application_manifest["format"] == APPLICATION_MANIFEST_FORMAT
    assert app.application_manifest["tool_manifest_id"] == app.tool_manifest[
        "tool_manifest_id"
    ]
    assert app.application_manifest["capabilities"] == list(app.capability_manifest)
    assert app.application_manifest["configuration_variables"] == list(
        PUBLIC_CONFIGURATION_VARIABLES
    )
    assert app.application_manifest["configuration_variables"] == sorted(
        app.application_manifest["configuration_variables"]
    )
    assert len(app.application_manifest["application_id"]) == 64
    assert server._mcp_server.instructions == "composed instructions"
    assert server.removed == ["weave_help"]
    assert server.added == ["weave_help"]


def test_tool_manifest_identity_is_order_independent() -> None:
    names = ["weave_help", "project_initialize", "program_validate", "branch_merge"]
    left = build_tool_manifest([_contract(name) for name in names])
    right = build_tool_manifest([_contract(name) for name in reversed(names)])

    assert left == right


@pytest.mark.parametrize(
    "changed",
    [
        _contract("program_validate", input_type="integer"),
        _contract("program_validate", output_type="string"),
        _contract("program_validate", description="Changed public description"),
    ],
)
def test_tool_contract_changes_manifest_identity(changed: dict[str, Any]) -> None:
    names = ["weave_help", "project_initialize", "program_validate", "branch_merge"]
    baseline_contracts = [_contract(name) for name in names]
    changed_contracts = [
        changed if contract["name"] == "program_validate" else contract
        for contract in baseline_contracts
    ]

    baseline = build_tool_manifest(baseline_contracts)
    modified = build_tool_manifest(changed_contracts)

    assert modified["tool_names"] == baseline["tool_names"]
    assert modified["tool_manifest_id"] != baseline["tool_manifest_id"]
    baseline_validate = next(
        tool for tool in baseline["tools"] if tool["name"] == "program_validate"
    )
    modified_validate = next(
        tool for tool in modified["tools"] if tool["name"] == "program_validate"
    )
    assert modified_validate["tool_contract_id"] != baseline_validate["tool_contract_id"]


def test_registered_contract_reads_fastmcp_metadata() -> None:
    server = _FakeFastMCP(
        {
            "sample": _tool(
                "sample",
                title="Sample title",
                annotations=SimpleNamespace(
                    model_dump=lambda **_: {"readOnlyHint": True}
                ),
                icons=[{"src": "https://example.invalid/icon.png"}],
                meta={"version": 2},
            )
        }
    )

    contracts = registered_tool_contracts(server)

    assert contracts == (
        {
            "name": "sample",
            "title": "Sample title",
            "description": "Tool sample",
            "input_schema": server.tools["sample"].parameters,
            "output_schema": server.tools["sample"].fn_metadata.output_schema,
            "annotations": server.tools["sample"].annotations,
            "icons": server.tools["sample"].icons,
            "meta": server.tools["sample"].meta,
        },
    )
    manifest = build_tool_manifest(contracts, required_tools=())
    assert manifest["tools"][0]["annotations"] == {"readOnlyHint": True}
    assert manifest["tools"][0]["meta"] == {"version": 2}


def test_missing_required_tool_is_rejected() -> None:
    with pytest.raises(ApplicationCompositionError, match="missing required tools"):
        build_tool_manifest([_contract("weave_help")])


def test_invalid_required_tool_name_is_rejected_as_composition_error() -> None:
    with pytest.raises(
        ApplicationCompositionError,
        match="required tool names must be non-empty strings",
    ):
        build_tool_manifest(
            [_contract("sample")],
            required_tools=[["invalid"]],  # type: ignore[list-item]
        )


def test_missing_tool_input_schema_is_rejected() -> None:
    server = _FakeFastMCP({"weave_help": _tool("weave_help")})
    server.tools["weave_help"].parameters = None  # type: ignore[assignment]

    with pytest.raises(ApplicationCompositionError, match="no mapping input schema"):
        registered_tool_contracts(server)


def test_non_string_registry_key_is_rejected_before_lookup() -> None:
    server = _FakeFastMCP()
    server.tools = {1: _tool("1")}  # type: ignore[assignment]

    with pytest.raises(
        ApplicationCompositionError,
        match="registry keys must be non-empty strings",
    ):
        registered_tool_contracts(server)


def test_unknown_contract_field_is_not_silently_dropped() -> None:
    contract = _contract("sample")
    contract["future_protocol_field"] = {"enabled": True}

    with pytest.raises(
        ApplicationCompositionError,
        match="unsupported fields",
    ):
        build_tool_manifest([contract], required_tools=())


def test_failed_model_dump_is_reported_as_composition_error() -> None:
    class _BrokenModel:
        def model_dump(self, **_: Any) -> Any:
            raise ValueError("cannot serialize")

    contract = _contract("sample")
    contract["annotations"] = _BrokenModel()

    with pytest.raises(
        ApplicationCompositionError,
        match="cannot serialize tool contract value",
    ):
        build_tool_manifest([contract], required_tools=())


def test_unknown_tool_registry_shape_is_rejected() -> None:
    with pytest.raises(ApplicationCompositionError, match="tool registry is unavailable"):
        registered_tool_names(SimpleNamespace())


def test_public_entrypoint_exposes_one_composed_application() -> None:
    from weave_jacquard import mcp_build as public_entrypoint

    assert public_entrypoint.PUBLIC_APP.server is public_entrypoint.mcp
    assert (
        public_entrypoint.PUBLIC_APP.capability_manifest
        == public_entrypoint.PUBLIC_CAPABILITY_MANIFEST
    )
    assert public_entrypoint.PUBLIC_APP.tool_manifest == public_entrypoint.PUBLIC_TOOL_MANIFEST
    assert (
        public_entrypoint.PUBLIC_APP.application_manifest
        == public_entrypoint.PUBLIC_APPLICATION_MANIFEST
    )
    assert public_entrypoint.PUBLIC_TOOL_MANIFEST["tool_names"] == sorted(
        public_entrypoint.PUBLIC_TOOL_MANIFEST["tool_names"]
    )
    assert "weave_help" in public_entrypoint.PUBLIC_TOOL_MANIFEST["tool_names"]
    assert "tested_merge_attest" in public_entrypoint.PUBLIC_TOOL_MANIFEST["tool_names"]
    assert "task_node_apply_batch" in public_entrypoint.PUBLIC_TOOL_MANIFEST["tool_names"]
    assert "revision_evidence_page" in public_entrypoint.PUBLIC_TOOL_MANIFEST["tool_names"]
    assert "branch_revert_preview" in public_entrypoint.PUBLIC_TOOL_MANIFEST["tool_names"]
    assert "branch_revert" in public_entrypoint.PUBLIC_TOOL_MANIFEST["tool_names"]
    assert all(
        tool["input_schema"]["type"] == "object"
        for tool in public_entrypoint.PUBLIC_TOOL_MANIFEST["tools"]
    )
