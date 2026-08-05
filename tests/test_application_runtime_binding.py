from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from weave_frontend.mcp_capabilities import (
    ApplicationContext,
    Capability,
    install_public_capabilities,
)
from weave_frontend.runtime import (
    RuntimeClosedError,
    RuntimeConfig,
    RuntimeServices,
    bind_application_runtime,
    clear_runtime_service,
    runtime_config,
    runtime_service_cache_info,
    runtime_services,
)


@dataclass
class _LowLevelServer:
    instructions: str = "legacy"


class _FakeFastMCP:
    def __init__(self) -> None:
        self._mcp_server = _LowLevelServer()
        self.tools: dict[str, Any] = {"weave_help": object()}

    def remove_tool(self, name: str) -> None:
        del self.tools[name]

    def add_tool(
        self,
        function: Any,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        del description
        self.tools[name or function.__name__] = function


def _runtime(tmp_path: Path, name: str) -> RuntimeServices:
    return RuntimeServices(
        RuntimeConfig.from_environ({"WEAVE_DB_PATH": str(tmp_path / f"{name}.db")})
    )


def test_runtime_binding_is_nested_and_restored(tmp_path: Path) -> None:
    process_runtime = runtime_services()
    left = _runtime(tmp_path, "left")
    right = _runtime(tmp_path, "right")

    with bind_application_runtime(left):
        assert runtime_services() is left
        assert runtime_config() is left.config
        with bind_application_runtime(right):
            assert runtime_services() is right
            assert runtime_config() is right.config
        assert runtime_services() is left

    assert runtime_services() is process_runtime


def test_runtime_binding_restores_after_installer_error(tmp_path: Path) -> None:
    process_runtime = runtime_services()
    bound = _runtime(tmp_path, "failing")

    with pytest.raises(RuntimeError, match="installer failed"), bind_application_runtime(bound):
        assert runtime_services() is bound
        raise RuntimeError("installer failed")

    assert runtime_services() is process_runtime


def test_concurrent_runtime_bindings_overlap_without_cross_contamination(
    tmp_path: Path,
) -> None:
    process_runtime = runtime_services()
    left = _runtime(tmp_path, "concurrent-left")
    right = _runtime(tmp_path, "concurrent-right")
    observations: list[tuple[str, RuntimeServices]] = []

    async def run() -> None:
        left_started = asyncio.Event()
        right_started = asyncio.Event()
        release = asyncio.Event()

        async def observe(
            name: str,
            selected: RuntimeServices,
            started: asyncio.Event,
            peer_started: asyncio.Event,
        ) -> None:
            with bind_application_runtime(selected):
                observations.append((f"{name}:before", runtime_services()))
                started.set()
                await peer_started.wait()
                await release.wait()
                observations.append((f"{name}:after", runtime_services()))

        left_task = asyncio.create_task(observe("left", left, left_started, right_started))
        right_task = asyncio.create_task(observe("right", right, right_started, left_started))
        await left_started.wait()
        await right_started.wait()
        release.set()
        await asyncio.gather(left_task, right_task)

    asyncio.run(run())

    assert observations[:2] == [
        ("left:before", left),
        ("right:before", right),
    ]
    assert dict(observations[2:]) == {
        "left:after": left,
        "right:after": right,
    }
    assert runtime_services() is process_runtime


def test_child_task_inherits_bound_runtime_at_creation(tmp_path: Path) -> None:
    process_runtime = runtime_services()
    bound = _runtime(tmp_path, "child")

    async def run() -> RuntimeServices:
        child_ready = asyncio.Event()
        release_child = asyncio.Event()

        async def child() -> RuntimeServices:
            child_ready.set()
            await release_child.wait()
            return runtime_services()

        with bind_application_runtime(bound):
            task = asyncio.create_task(child())
            await child_ready.wait()

        assert runtime_services() is process_runtime
        release_child.set()
        return await task

    assert asyncio.run(run()) is bound
    assert runtime_services() is process_runtime


def test_bound_cache_operations_do_not_touch_process_runtime(tmp_path: Path) -> None:
    process_runtime = runtime_services()
    bound = _runtime(tmp_path, "cache-bound")
    bound.service(
        "binding_probe",
        lambda: SimpleNamespace(runtime="bound"),
        origin="tests.binding_probe",
    )

    with bind_application_runtime(bound):
        assert runtime_service_cache_info("binding_probe").currsize == 1
        clear_runtime_service("binding_probe")
        assert runtime_service_cache_info("binding_probe").currsize == 0

    assert not process_runtime.service_initialized("binding_probe")


def test_capability_loading_and_installation_use_context_runtime(
    tmp_path: Path,
) -> None:
    process_runtime = runtime_services()
    application_runtime = _runtime(tmp_path, "application")
    server = _FakeFastMCP()
    context = ApplicationContext(server=server, runtime=application_runtime)
    observed: list[tuple[str, RuntimeServices, RuntimeConfig]] = []

    def loader(name: str) -> ModuleType:
        if name == "weave_frontend.mcp_revert_guidance":
            return SimpleNamespace(  # type: ignore[return-value]
                INSTRUCTIONS="bound instructions",
                weave_help=lambda topic="workflow": {"topic": topic},
            )

        observed.append((f"load:{name}", runtime_services(), runtime_config()))
        module = ModuleType(name)
        if name == "example.legacy":

            def install_capability(selected: ApplicationContext) -> None:
                services = runtime_services()
                services.service(
                    "legacy_probe",
                    lambda: runtime_config().database_path,
                    origin="tests.legacy_probe",
                )
                observed.append(("install:legacy", services, runtime_config()))
                assert selected is context

            module.install_capability = install_capability  # type: ignore[attr-defined]
        else:

            def install_capability(selected: ApplicationContext) -> None:
                observed.append(("install:context", runtime_services(), runtime_config()))
                assert selected is context

            module.install_capability = install_capability  # type: ignore[attr-defined]
        return module

    install_public_capabilities(
        context,
        capabilities=(
            Capability("legacy", "example.legacy"),
            Capability("context", "example.context", ("legacy",)),
        ),
        module_loader=loader,
    )

    assert observed
    assert all(runtime is application_runtime for _event, runtime, _config in observed)
    assert all(config is application_runtime.config for _event, _runtime, config in observed)
    assert application_runtime.service_initialized("legacy_probe")
    assert not process_runtime.service_initialized("legacy_probe")
    assert server._mcp_server.instructions == "bound instructions"


def test_closed_runtime_cannot_be_bound(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, "closed")
    runtime.close()

    with (
        pytest.raises(RuntimeClosedError, match="closed runtime"),
        bind_application_runtime(runtime),
    ):
        raise AssertionError("closed binding must not start")


def test_closed_inherited_runtime_fails_closed(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, "closed-inherited")

    with bind_application_runtime(runtime):
        runtime.close()
        with pytest.raises(RuntimeClosedError, match="bound Jacquard runtime"):
            runtime_services()
