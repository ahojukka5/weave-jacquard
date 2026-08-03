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


def test_context_core_staging_preserves_contracts_and_callables(
    tmp_path: Path,
) -> None:
    source = FastMCPRegistryAdapter(mcp_server.mcp)
    source_objects = dict(source.tool_objects())
    source_contracts = {
        contract["name"]: contract for contract in source.tool_contracts()
    }
    expected_names = tuple(
        sorted(name for name in CORE_TOOL_NAMES if name in source_objects)
    )
    expected_contracts = tuple(source_contracts[name] for name in expected_names)

    target = FastMCP("context-core-tools")
    adapter = FastMCPRegistryAdapter(target)
    runtime = _runtime(tmp_path)
    context = ApplicationContext(server=target, runtime=runtime)

    assert adapter.tool_names(allow_empty=True) == ()
    assert "expected_revision_id" in (
        source_contracts["program_create"]["input_schema"]["properties"]
    )
    assert "expected_revision_id" in (
        source_contracts["context_add"]["input_schema"]["properties"]
    )

    try:
        installed = install_context_core_tools(context, mcp_server.mcp)
        first_objects = dict(adapter.tool_objects())

        assert installed == expected_names
        assert adapter.tool_contracts() == expected_contracts
        for name in installed:
            assert first_objects[name] is not source_objects[name]
            assert first_objects[name].fn is source_objects[name].fn

        repeated = install_context_core_tools(context, mcp_server.mcp)
        second_objects = dict(adapter.tool_objects())

        assert repeated == installed
        assert adapter.tool_contracts() == expected_contracts
        for name in installed:
            assert second_objects[name] is not first_objects[name]
            assert second_objects[name].fn is source_objects[name].fn
    finally:
        runtime.close()
