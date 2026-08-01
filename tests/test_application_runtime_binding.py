from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from weave_frontend.application_runtime_binding import bind_application_runtime
from weave_frontend.mcp_capabilities import (
    ApplicationContext,
    Capability,
    install_public_capabilities,
)
from weave_frontend.runtime_config import RuntimeConfig
from weave_frontend.runtime_container import (
    RuntimeClosedError,
    RuntimeServices,
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
        RuntimeConfig.from_environ(
            {"WEAVE_DB_PATH": str(tmp_path / f"{name}.db")}
        )
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

            def install_capability() -> None:
                services = runtime_services()
                services.service(
                    "legacy_probe",
                    lambda: runtime_config().database_path,
                    origin="tests.legacy_probe",
                )
                observed.append(("install:legacy", services, runtime_config()))

            module.install_capability = install_capability  # type: ignore[attr-defined]
        else:

            def install_capability(selected: ApplicationContext) -> None:
                observed.append(
                    ("install:context", runtime_services(), runtime_config())
                )
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
    assert all(
        runtime is application_runtime
        for _event, runtime, _config in observed
    )
    assert all(
        config is application_runtime.config
        for _event, _runtime, config in observed
    )
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
