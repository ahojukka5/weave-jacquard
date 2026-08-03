from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from weave_frontend.application_tool_registration import (
    bind_registered_application_tools,
)
from weave_frontend.fastmcp_registry import FastMCPRegistryError
from weave_frontend.mcp_capabilities import ApplicationContext
from weave_frontend.runtime_config import RuntimeConfig
from weave_frontend.runtime_container import RuntimeServices, runtime_services


@dataclass
class _Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    fn: Any
    is_async: bool = False

    def model_copy(self, *, update: dict[str, Any]) -> _Tool:
        return replace(self, **update)


class _Server:
    def __init__(self, tool: _Tool) -> None:
        self.tools = {tool.name: tool}


def _tool(function: Any) -> _Tool:
    return _Tool(
        name="runtime_probe",
        description="Report the selected runtime",
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        fn=function,
    )


def _runtime(tmp_path: Path, name: str) -> RuntimeServices:
    return RuntimeServices(
        RuntimeConfig.from_environ(
            {"WEAVE_DB_PATH": str(tmp_path / f"{name}.db")}
        )
    )


def test_rebinding_uses_the_retained_canonical_callable(tmp_path: Path) -> None:
    process_runtime = runtime_services()
    left_runtime = _runtime(tmp_path, "left")
    right_runtime = _runtime(tmp_path, "right")
    server = _Server(_tool(runtime_services))

    bind_registered_application_tools(
        ApplicationContext(server=server, runtime=left_runtime)
    )
    left_bound = server.tools["runtime_probe"]
    assert asyncio.run(left_bound.fn()) is left_runtime

    bind_registered_application_tools(
        ApplicationContext(server=server, runtime=right_runtime)
    )
    right_bound = server.tools["runtime_probe"]

    assert right_bound is not left_bound
    assert asyncio.run(right_bound.fn()) is right_runtime
    assert asyncio.run(left_bound.fn()) is left_runtime
    assert runtime_services() is process_runtime


def test_rebinding_rejects_invalid_canonical_callable(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, "invalid")

    def probe() -> RuntimeServices:
        return runtime_services()

    probe.__weave_jacquard_canonical_tool_function__ = object()
    server = _Server(_tool(probe))

    with pytest.raises(FastMCPRegistryError, match="invalid canonical callable"):
        bind_registered_application_tools(
            ApplicationContext(server=server, runtime=runtime)
        )
