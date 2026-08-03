from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from weave_frontend import mcp_server
from weave_frontend.context_tool_registration import (
    CORE_TOOL_NAMES,
    install_context_core_tools,
)
from weave_frontend.fastmcp_registry import FastMCPRegistryAdapter
from weave_frontend.mcp_capabilities import ApplicationContext
from weave_frontend.runtime_config import RuntimeConfig
from weave_frontend.runtime_container import RuntimeServices


def _runtime(tmp_path: Path) -> RuntimeServices:
    return RuntimeServices(
        RuntimeConfig.from_environ(
            {"WEAVE_DB_PATH": str(tmp_path / "context-tools.db")}
        )
    )


def test_context_core_localization_preserves_contracts_and_callables(
    tmp_path: Path,
) -> None:
    target = FastMCP("context-core-tools")
    adapter = FastMCPRegistryAdapter(target)
    adapter.replace_tools_from(mcp_server.mcp)
    before_contracts = adapter.tool_contracts()
    contracts_by_name = {
        contract["name"]: contract for contract in before_contracts
    }
    transferred_objects = dict(adapter.tool_objects())
    expected_names = tuple(
        name for name in CORE_TOOL_NAMES if name in transferred_objects
    )
    runtime = _runtime(tmp_path)
    context = ApplicationContext(server=target, runtime=runtime)

    assert "expected_revision_id" in (
        contracts_by_name["program_create"]["input_schema"]["properties"]
    )
    assert "expected_revision_id" in (
        contracts_by_name["context_add"]["input_schema"]["properties"]
    )

    try:
        installed = install_context_core_tools(context)
        first_objects = dict(adapter.tool_objects())

        assert installed == expected_names
        assert adapter.tool_contracts() == before_contracts
        for name in installed:
            assert first_objects[name] is not transferred_objects[name]
            assert first_objects[name].fn is transferred_objects[name].fn
        assert first_objects["weave_help"] is transferred_objects["weave_help"]

        repeated = install_context_core_tools(context)
        second_objects = dict(adapter.tool_objects())

        assert repeated == installed
        assert adapter.tool_contracts() == before_contracts
        for name in installed:
            assert second_objects[name] is not first_objects[name]
            assert second_objects[name].fn is first_objects[name].fn
        assert second_objects["weave_help"] is first_objects["weave_help"]
    finally:
        runtime.close()
