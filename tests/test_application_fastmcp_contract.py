from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from weave_frontend.application import build_tool_manifest, registered_tool_contracts


def test_real_fastmcp_contract_is_schema_complete() -> None:
    server = FastMCP("contract-test")

    @server.tool()
    def sample(value: int, enabled: bool = False) -> dict[str, int]:
        """Return the selected value when enabled."""

        return {"result": value if enabled else 0}

    contracts = registered_tool_contracts(server)
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
