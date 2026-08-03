from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from weave_frontend.application_tool_registration import (
    finalize_registered_application_tools,
)
from weave_frontend.context_capability_tool_registration import (
    capability_tool_names,
    install_context_capability_tools,
)
from weave_frontend.fastmcp_registry import (
    FastMCPRegistryAdapter,
    FastMCPRegistryError,
)
from weave_frontend.mcp_capabilities import (
    PUBLIC_CAPABILITIES,
    ApplicationContext,
    install_public_capabilities,
)
from weave_frontend.runtime_config import RuntimeConfig
from weave_frontend.runtime_container import RuntimeServices, runtime_services


@dataclass
class _LowLevelServer:
    instructions: str = "legacy"


@dataclass
class _Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    fn: Any
    is_async: bool = False
    generation: int = 0
    output_schema: dict[str, Any] | None = None
    title: str | None = None
    annotations: Any = None
    icons: Any = None
    meta: Any = None

    def model_copy(self, *, update: dict[str, Any]) -> _Tool:
        return replace(self, generation=self.generation + 1, **update)


class _Server:
    def __init__(self, tools: dict[str, _Tool] | None = None) -> None:
        self._mcp_server = _LowLevelServer()
        self.tools = dict(tools or {})

    def remove_tool(self, name: str) -> None:
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
            function=function,
            description=description,
        )


def _function(module_name: str) -> Any:
    def tool_function() -> RuntimeServices:
        return runtime_services()

    tool_function.__module__ = module_name
    return tool_function


def _tool(
    name: str,
    *,
    function: Any | None = None,
    description: str | None = None,
) -> _Tool:
    return _Tool(
        name=name,
        description=description or f"Tool {name}",
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        fn=function or _function("example.tools"),
    )


def _runtime(tmp_path: Path, name: str) -> RuntimeServices:
    return RuntimeServices(
        RuntimeConfig.from_environ(
            {"WEAVE_DB_PATH": str(tmp_path / f"{name}.db")}
        )
    )


def test_owner_tools_are_cloned_explicitly_before_finalization(
    tmp_path: Path,
) -> None:
    owned_module = ModuleType("example.capability")
    foreign_module = ModuleType("example.foreign")
    owned = _tool("owned", function=_function(owned_module.__name__))
    foreign = _tool("foreign", function=_function(foreign_module.__name__))
    source = _Server({"owned": owned, "foreign": foreign})
    target = _Server({"stale": _tool("stale")})
    runtime = _runtime(tmp_path, "selective")
    context = ApplicationContext(server=target, runtime=runtime)

    try:
        assert capability_tool_names(source, owned_module) == ("owned",)
        assert capability_tool_names(source, foreign_module) == ("foreign",)

        install_context_capability_tools(context, source, owned_module)
        with pytest.raises(FastMCPRegistryError, match="incomplete"):
            finalize_registered_application_tools(context, source)

        install_context_capability_tools(context, source, foreign_module)
        finalized = finalize_registered_application_tools(context, source)

        assert finalized == ("foreign", "owned")
        assert set(target.tools) == {"foreign", "owned"}
        assert target.tools["owned"] is not owned
        assert target.tools["foreign"] is not foreign
        assert target.tools["owned"].fn is owned.fn
        assert target.tools["foreign"].fn is foreign.fn
        assert target.tools["owned"].generation == 1
        assert target.tools["foreign"].generation == 1
        assert FastMCPRegistryAdapter(target).tool_contracts() == (
            FastMCPRegistryAdapter(source).tool_contracts()
        )
    finally:
        runtime.close()


def test_public_composition_preserves_explicit_tool_lineage(
    tmp_path: Path,
) -> None:
    source_tools = {
        "weave_help": _tool(
            "weave_help",
            function=_function("weave_frontend.mcp_server"),
        ),
        "project_initialize": _tool(
            "project_initialize",
            function=_function("weave_frontend.mcp_server"),
        ),
        "agent_checkpoint_publish": _tool(
            "agent_checkpoint_publish",
            function=_function("weave_frontend.mcp_agent_checkpoint"),
        ),
        "build_validate": _tool(
            "build_validate",
            function=_function("weave_frontend.mcp_build"),
        ),
    }
    source = _Server(source_tools)
    target = _Server({"stale": _tool("stale")})
    runtime = _runtime(tmp_path, "canonical")
    context = ApplicationContext(server=target, runtime=runtime)

    def loader(name: str) -> ModuleType:
        if name == "weave_frontend.mcp_server":
            module = ModuleType(name)
            module.mcp = source  # type: ignore[attr-defined]
            return module
        if name == "weave_frontend.mcp_revert_guidance":
            return SimpleNamespace(  # type: ignore[return-value]
                INSTRUCTIONS="application instructions",
                weave_help=lambda topic="workflow": {"topic": topic},
            )

        module = ModuleType(name)
        if name in {
            "weave_frontend.mcp_test_targets",
            "weave_frontend.mcp_merge_test_impact",
            "weave_frontend.mcp_merge_candidate_test_runs",
        }:
            module.install_metadata_aware_merge_services = (  # type: ignore[attr-defined]
                lambda: None
            )
        if name == "weave_frontend.mcp_artifact_storage":
            module.artifact_quota = lambda: None  # type: ignore[attr-defined]
        return module

    try:
        install_public_capabilities(
            context,
            capabilities=PUBLIC_CAPABILITIES,
            module_loader=loader,
        )

        assert set(target.tools) == set(source_tools)
        assert "stale" not in target.tools
        assert all(target.tools[name] is not source_tools[name] for name in source_tools)
        assert target.tools["agent_checkpoint_publish"].generation == 2
        assert target.tools["project_initialize"].generation == 2
        assert target.tools["build_validate"].generation == 2
        assert target.tools["weave_help"].generation == 1
        assert all(tool.is_async is True for tool in target.tools.values())
        assert asyncio.run(target.tools["agent_checkpoint_publish"].fn()) is runtime
        assert asyncio.run(target.tools["build_validate"].fn()) is runtime
        assert target._mcp_server.instructions == "application instructions"
    finally:
        runtime.close()
