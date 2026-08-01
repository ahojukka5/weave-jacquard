from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP

from weave_frontend.application import build_tool_manifest
from weave_frontend.fastmcp_registry import (
    FastMCPRegistryAdapter,
    FastMCPRegistryError,
)


def _tool(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        title=None,
        description=f"Tool {name}",
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        output_schema=None,
        fn_metadata=SimpleNamespace(output_schema=None),
        annotations=None,
        icons=None,
        meta=None,
    )


def test_real_fastmcp_contract_is_schema_complete() -> None:
    server = FastMCP("contract-test")

    @server.tool()
    def sample(value: int, enabled: bool = False) -> dict[str, int]:
        """Return the selected value when enabled."""

        return {"result": value if enabled else 0}

    contracts = FastMCPRegistryAdapter(server).tool_contracts()
    manifest = build_tool_manifest(contracts, required_tools=())

    assert len(contracts) == 1
    contract = contracts[0]
    assert contract["name"] == "sample"
    assert contract["description"] == "Return the selected value when enabled."
    assert contract["input_schema"]["type"] == "object"
    assert contract["input_schema"]["properties"]["value"]["type"] == "integer"
    assert contract["input_schema"]["properties"]["enabled"]["type"] == "boolean"
    assert contract["input_schema"]["required"] == ["value"]
    assert contract["output_schema"] is not None
    assert contract["output_schema"]["type"] == "object"

    assert manifest["tool_names"] == ["sample"]
    assert manifest["tools"][0]["name"] == "sample"
    assert len(manifest["tools"][0]["tool_contract_id"]) == 64
    assert len(manifest["tool_manifest_id"]) == 64


def test_adapter_prefers_fastmcp_manager_registry() -> None:
    manager_tool = _tool("manager")
    fallback_tool = _tool("fallback")
    server = SimpleNamespace(
        _tool_manager=SimpleNamespace(_tools={"manager": manager_tool}),
        tools={"fallback": fallback_tool},
    )

    adapter = FastMCPRegistryAdapter(server)

    assert adapter.tool_names() == ("manager",)
    assert adapter.tool_contracts()[0]["name"] == "manager"


def test_adapter_supports_mapping_backed_test_server() -> None:
    tool = _tool("sample")
    tool._meta = {"source": "legacy"}
    server = SimpleNamespace(tools={"sample": tool})

    contracts = FastMCPRegistryAdapter(server).tool_contracts()

    assert contracts == (
        {
            "name": "sample",
            "title": None,
            "description": "Tool sample",
            "input_schema": tool.parameters,
            "output_schema": None,
            "annotations": None,
            "icons": None,
            "meta": {"source": "legacy"},
        },
    )


@pytest.mark.parametrize(
    ("server", "message"),
    [
        (SimpleNamespace(), "tool registry is unavailable"),
        (SimpleNamespace(tools={}), "registered no tools"),
        (
            SimpleNamespace(tools={1: _tool("1")}),
            "registry keys must be non-empty strings",
        ),
    ],
)
def test_adapter_rejects_unsupported_registry_contracts(
    server: Any,
    message: str,
) -> None:
    with pytest.raises(FastMCPRegistryError, match=message):
        FastMCPRegistryAdapter(server).tool_contracts()
