from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType, ModuleType, SimpleNamespace
from typing import Any

import pytest

from weave_frontend.application import JacquardApp
from weave_frontend.application_tool_registration import (
    install_registered_application_tools,
)
from weave_frontend.fastmcp_registry import (
    FastMCPRegistryAdapter,
    FastMCPRegistryError,
)
from weave_frontend.mcp_capabilities import (
    PUBLIC_CAPABILITIES,
    ApplicationContext,
    Capability,
    install_public_capabilities,
)
from weave_frontend.runtime_config import RuntimeConfig
from weave_frontend.runtime_container import RuntimeServices


@dataclass
class _LowLevelServer:
    instructions: str = "legacy"


@dataclass
class _Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    output_schema: dict[str, Any] | None = None
    title: str | None = None
    annotations: Any = None
    icons: Any = None
    meta: Any = None


class _Server:
    def __init__(self, tools: dict[str, Any] | None = None) -> None:
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
        self.tools[tool_name] = _tool(tool_name, description=description)
        self.added.append(tool_name)


def _tool(name: str, *, description: str | None = None) -> _Tool:
    return _Tool(
        name=name,
        description=description or f"Tool {name}",
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    )


def _runtime(tmp_path: Path, name: str) -> RuntimeServices:
    return RuntimeServices(
        RuntimeConfig.from_environ(
            {"WEAVE_DB_PATH": str(tmp_path / f"{name}.db")}
        )
    )


def test_registry_transfer_preserves_exact_tool_objects() -> None:
    source_tools = {
        "alpha": _tool("alpha"),
        "beta": _tool("beta"),
    }
    source = _Server(source_tools)
    target = _Server({"stale": _tool("stale")})

    names = FastMCPRegistryAdapter(target).replace_tools_from(source)

    assert names == ("alpha", "beta")
    assert set(target.tools) == set(source_tools)
    assert target.tools["alpha"] is source_tools["alpha"]
    assert target.tools["beta"] is source_tools["beta"]
    assert FastMCPRegistryAdapter(target).tool_contracts() == (
        FastMCPRegistryAdapter(source).tool_contracts()
    )


def test_registry_transfer_rejects_immutable_target() -> None:
    source = _Server({"sample": _tool("sample")})
    target = SimpleNamespace(tools=MappingProxyType({"stale": _tool("stale")}))

    with pytest.raises(FastMCPRegistryError, match="must be mutable"):
        FastMCPRegistryAdapter(target).replace_tools_from(source)

    assert tuple(target.tools) == ("stale",)


def test_application_registration_replaces_stale_target_contracts(
    tmp_path: Path,
) -> None:
    source = _Server(
        {
            "weave_help": _tool("weave_help"),
            "project_initialize": _tool("project_initialize"),
        }
    )
    target = _Server({"stale": _tool("stale")})
    context = ApplicationContext(
        server=target,
        runtime=_runtime(tmp_path, "application"),
    )

    names = install_registered_application_tools(context, source)

    assert names == ("project_initialize", "weave_help")
    assert set(target.tools) == set(source.tools)
    assert all(target.tools[name] is source.tools[name] for name in names)


def test_custom_capability_graph_does_not_replace_target_registry(
    tmp_path: Path,
) -> None:
    target = _Server({"weave_help": _tool("weave_help"), "custom": _tool("custom")})
    context = ApplicationContext(
        server=target,
        runtime=_runtime(tmp_path, "custom"),
    )
    loaded: list[str] = []

    def loader(name: str) -> ModuleType:
        loaded.append(name)
        if name == "weave_frontend.mcp_revert_guidance":
            return SimpleNamespace(  # type: ignore[return-value]
                INSTRUCTIONS="custom instructions",
                weave_help=lambda topic="workflow": {"topic": topic},
            )
        return ModuleType(name)

    install_public_capabilities(
        context,
        capabilities=(Capability("custom", "example.custom"),),
        module_loader=loader,
    )

    assert "weave_frontend.mcp_server" not in loaded
    assert "custom" in target.tools


def test_public_capability_graph_transfers_registry_to_context_server(
    tmp_path: Path,
) -> None:
    source_tools = {
        "weave_help": _tool("weave_help"),
        "project_initialize": _tool("project_initialize"),
        "program_validate": _tool("program_validate"),
        "branch_merge": _tool("branch_merge"),
    }
    source = _Server(source_tools)
    target = _Server({"stale": _tool("stale")})
    runtime = _runtime(tmp_path, "public")

    def loader(name: str) -> ModuleType:
        if name == "weave_frontend.mcp_server":
            module = ModuleType(name)
            module.mcp = source  # type: ignore[attr-defined]
            return module
        if name == "weave_frontend.mcp_revert_guidance":
            return SimpleNamespace(  # type: ignore[return-value]
                INSTRUCTIONS="public instructions",
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

    app = JacquardApp.compose(
        target,
        runtime=runtime,
        capabilities=PUBLIC_CAPABILITIES,
        module_loader=loader,
    )

    assert app.server is target
    assert app.context.runtime is runtime
    assert "stale" not in target.tools
    assert target.tools["project_initialize"] is source_tools["project_initialize"]
    assert target.tools["program_validate"] is source_tools["program_validate"]
    assert target.tools["branch_merge"] is source_tools["branch_merge"]
    assert app.tool_manifest["tool_names"] == [
        "branch_merge",
        "program_validate",
        "project_initialize",
        "weave_help",
    ]
    assert target._mcp_server.instructions == "public instructions"
    assert target.removed == ["weave_help"]
    assert target.added == ["weave_help"]
