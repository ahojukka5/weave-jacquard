from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType, ModuleType, SimpleNamespace
from typing import Any

import pytest

from weave_frontend.application import JacquardApp
from weave_frontend.application_tool_registration import (
    bind_registered_application_tools,
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
from weave_frontend.runtime import RuntimeConfig, RuntimeServices, runtime_services


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
    output_schema: dict[str, Any] | None = None
    title: str | None = None
    annotations: Any = None
    icons: Any = None
    meta: Any = None

    def model_copy(self, *, update: dict[str, Any]) -> _Tool:
        return replace(self, **update)


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
        self.tools[tool_name] = _tool(
            tool_name,
            description=description,
            function=function,
        )
        self.added.append(tool_name)


def _tool(
    name: str,
    *,
    description: str | None = None,
    function: Any | None = None,
) -> _Tool:
    if function is None:

        def function(name: str = name) -> str:
            return name

    return _Tool(
        name=name,
        description=description or f"Tool {name}",
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        fn=function,
        is_async=asyncio.iscoroutinefunction(function),
    )


def _runtime(tmp_path: Path, name: str) -> RuntimeServices:
    return RuntimeServices(
        RuntimeConfig.from_environ({"WEAVE_DB_PATH": str(tmp_path / f"{name}.db")})
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


def test_registry_transform_rejects_contract_changes_before_replacement() -> None:
    source = _Server({"sample": _tool("sample")})
    target = _Server({"stale": _tool("stale")})

    def change_description(_name: str, tool: _Tool) -> _Tool:
        return tool.model_copy(update={"description": "changed"})

    with pytest.raises(FastMCPRegistryError, match="transformation changed"):
        FastMCPRegistryAdapter(target).replace_tools_from(
            source,
            transform=change_description,
        )

    assert tuple(target.tools) == ("stale",)


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


def test_application_binding_clones_tools_and_preserves_contracts(
    tmp_path: Path,
) -> None:
    process_runtime = runtime_services()
    application_runtime = _runtime(tmp_path, "bound")
    source_tool = _tool(
        "runtime_probe",
        function=lambda: runtime_services(),
    )
    server = _Server({"runtime_probe": source_tool})
    context = ApplicationContext(server=server, runtime=application_runtime)
    contracts = FastMCPRegistryAdapter(server).tool_contracts()

    names = bind_registered_application_tools(context)
    clone = server.tools["runtime_probe"]

    assert names == ("runtime_probe",)
    assert clone is not source_tool
    assert clone.is_async is True
    assert FastMCPRegistryAdapter(server).tool_contracts() == contracts
    assert asyncio.run(clone.fn()) is application_runtime
    assert runtime_services() is process_runtime


def test_overlapping_application_calls_are_runtime_isolated(
    tmp_path: Path,
) -> None:
    process_runtime = runtime_services()
    left_runtime = _runtime(tmp_path, "left")
    right_runtime = _runtime(tmp_path, "right")
    events: list[tuple[str, RuntimeServices]] = []

    async def run_calls() -> tuple[RuntimeServices, RuntimeServices]:
        left_started = asyncio.Event()
        right_started = asyncio.Event()
        release = asyncio.Event()

        async def left_call() -> RuntimeServices:
            events.append(("left:start", runtime_services()))
            left_started.set()
            await right_started.wait()
            await release.wait()
            events.append(("left:end", runtime_services()))
            return runtime_services()

        async def right_call() -> RuntimeServices:
            events.append(("right:start", runtime_services()))
            right_started.set()
            await left_started.wait()
            await release.wait()
            events.append(("right:end", runtime_services()))
            return runtime_services()

        left_server = _Server({"probe": _tool("probe", function=left_call)})
        right_server = _Server({"probe": _tool("probe", function=right_call)})
        bind_registered_application_tools(
            ApplicationContext(server=left_server, runtime=left_runtime)
        )
        bind_registered_application_tools(
            ApplicationContext(server=right_server, runtime=right_runtime)
        )

        left_task = asyncio.create_task(left_server.tools["probe"].fn())
        await left_started.wait()
        right_task = asyncio.create_task(right_server.tools["probe"].fn())
        await right_started.wait()
        assert events == [
            ("left:start", left_runtime),
            ("right:start", right_runtime),
        ]
        release.set()
        results = await asyncio.gather(left_task, right_task)
        return results[0], results[1]

    assert asyncio.run(run_calls()) == (left_runtime, right_runtime)
    assert events[:2] == [
        ("left:start", left_runtime),
        ("right:start", right_runtime),
    ]
    assert dict(events[2:]) == {
        "left:end": left_runtime,
        "right:end": right_runtime,
    }
    assert runtime_services() is process_runtime


def test_nested_same_runtime_invocation_is_reentrant(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, "nested")
    server = _Server()
    inner = _tool("inner", function=lambda: runtime_services())

    async def outer_call() -> RuntimeServices:
        return await server.tools["inner"].fn()

    server.tools = {
        "inner": inner,
        "outer": _tool("outer", function=outer_call),
    }
    bind_registered_application_tools(ApplicationContext(server=server, runtime=runtime))

    assert asyncio.run(server.tools["outer"].fn()) is runtime


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
    assert target.tools["custom"].is_async is False


def test_public_capability_graph_binds_registry_to_context_runtime(
    tmp_path: Path,
) -> None:
    source_tools = {
        "weave_help": _tool("weave_help"),
        "project_initialize": _tool(
            "project_initialize",
            function=lambda: runtime_services(),
        ),
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
    assert target.tools["project_initialize"] is not source_tools["project_initialize"]
    assert target.tools["program_validate"] is not source_tools["program_validate"]
    assert target.tools["branch_merge"] is not source_tools["branch_merge"]
    assert all(tool.is_async is True for tool in target.tools.values())
    assert asyncio.run(target.tools["project_initialize"].fn()) is runtime
    assert app.tool_manifest["tool_names"] == [
        "branch_merge",
        "program_validate",
        "project_initialize",
        "weave_help",
    ]
    assert target._mcp_server.instructions == "public instructions"
    assert target.removed == ["weave_help"]
    assert target.added == ["weave_help"]
