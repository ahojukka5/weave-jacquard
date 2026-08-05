from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from weave_frontend.application_tool_registration import (
    bind_registered_application_tools,
)
from weave_frontend.mcp_capabilities import ApplicationContext
from weave_frontend.runtime_config import RuntimeConfig
from weave_frontend.runtime_container import RuntimeServices, runtime_services


@dataclass
class _Tool:
    name: str
    fn: Any
    parameters: dict[str, Any]
    description: str = "Runtime probe"
    is_async: bool = True
    output_schema: dict[str, Any] | None = None
    title: str | None = None
    annotations: Any = None
    icons: Any = None
    meta: Any = None

    def model_copy(self, *, update: dict[str, Any]) -> _Tool:
        return replace(self, **update)


@dataclass
class _Server:
    tools: dict[str, _Tool]


def _runtime(tmp_path: Path, name: str) -> RuntimeServices:
    return RuntimeServices(
        RuntimeConfig.from_environ({"WEAVE_DB_PATH": str(tmp_path / f"{name}.db")})
    )


def _tool(name: str, function: Any) -> _Tool:
    return _Tool(
        name=name,
        fn=function,
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    )


def test_inherited_runtime_context_reacquires_after_parent_returns(
    tmp_path: Path,
) -> None:
    process_runtime = runtime_services()
    runtime = _runtime(tmp_path, "inherited")
    release_child: asyncio.Event
    children: list[asyncio.Task[RuntimeServices]] = []
    server = _Server(tools={})

    async def inner_call() -> RuntimeServices:
        return runtime_services()

    async def delayed_inner() -> RuntimeServices:
        await release_child.wait()
        return await server.tools["inner"].fn()

    async def spawn_child() -> None:
        children.append(asyncio.create_task(delayed_inner()))

    server.tools = {
        "inner": _tool("inner", inner_call),
        "spawn": _tool("spawn", spawn_child),
    }
    bind_registered_application_tools(ApplicationContext(server=server, runtime=runtime))

    async def run_calls() -> RuntimeServices:
        nonlocal release_child
        release_child = asyncio.Event()
        await server.tools["spawn"].fn()
        assert runtime_services() is process_runtime
        release_child.set()
        return await children[0]

    assert asyncio.run(run_calls()) is runtime
    assert runtime_services() is process_runtime
