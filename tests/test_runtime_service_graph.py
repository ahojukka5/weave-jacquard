from __future__ import annotations

import inspect
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

import weave_frontend.mcp_build as build_module
import weave_frontend.mcp_concurrent_nodes as concurrent_nodes
import weave_frontend.mcp_server as server_module
import weave_frontend.runtime_container as runtime_module
from weave_frontend.mcp_runtime_identity import RuntimeIdentityWithServices
from weave_frontend.runtime_config import RuntimeConfig
from weave_frontend.runtime_container import (
    RUNTIME_SERVICE_GRAPH_FORMAT,
    RuntimeServiceCycleError,
    RuntimeServices,
    close_runtime_services,
    install_runtime_services,
    runtime_service,
)


class _Closeable:
    def __init__(self, name: str, closed: list[str]) -> None:
        self.name = name
        self.closed = closed

    def close(self) -> None:
        self.closed.append(self.name)


def _config(tmp_path: Path) -> RuntimeConfig:
    return RuntimeConfig.from_environ(
        {"WEAVE_DB_PATH": str(tmp_path / "runtime.db")}
    )


@contextmanager
def _isolated_process_runtime() -> Iterator[None]:
    with runtime_module._runtime_lock:
        previous_config = runtime_module._runtime_config
        previous_services = runtime_module._runtime_services
        runtime_module._runtime_config = None
        runtime_module._runtime_services = None
    try:
        yield
    finally:
        close_runtime_services()
        with runtime_module._runtime_lock:
            runtime_module._runtime_config = previous_config
            runtime_module._runtime_services = previous_services


@contextmanager
def _temporary_runtime_service(name: str) -> Iterator[None]:
    with runtime_module._declaration_lock:
        previous = runtime_module._runtime_service_declarations.get(name)
    try:
        yield
    finally:
        with runtime_module._declaration_lock:
            if previous is None:
                runtime_module._runtime_service_declarations.pop(name, None)
            else:
                runtime_module._runtime_service_declarations[name] = previous


def test_runtime_service_graph_records_dependencies_and_closes_in_reverse_order(
    tmp_path: Path,
) -> None:
    closed: list[str] = []
    services = RuntimeServices(_config(tmp_path))

    def dependency() -> _Closeable:
        return _Closeable("dependency", closed)

    def dependent() -> _Closeable:
        services.service("dependency", dependency)
        return _Closeable("dependent", closed)

    graph_before = services.service_manifest(include_state=False)
    first = services.service(
        "dependent",
        dependent,
        depends_on=("dependency",),
    )
    assert services.service("dependent", dependent) is first

    manifest = services.service_manifest()
    assert manifest["format"] == RUNTIME_SERVICE_GRAPH_FORMAT
    assert manifest["service_count"] >= 4
    assert manifest["initialized_service_count"] == 2
    assert manifest["initialized_services"] == ["dependency", "dependent"]
    assert len(manifest["service_graph_id"]) == 64
    entries = {item["name"]: item for item in manifest["services"]}
    assert entries["dependent"]["depends_on"] == ["dependency"]
    assert "initialized" not in entries["dependent"]
    assert graph_before["service_graph_id"] != manifest["service_graph_id"]

    state_free = services.service_manifest(include_state=False)
    services.service("dependent", dependent)
    assert services.service_manifest(include_state=False) == state_free

    services.close()
    services.close()
    assert closed == ["dependent", "dependency"]


def test_close_order_uses_declared_dependencies_not_creation_order(
    tmp_path: Path,
) -> None:
    closed: list[str] = []
    services = RuntimeServices(_config(tmp_path))

    services.service(
        "dependent",
        lambda: _Closeable("dependent", closed),
        depends_on=("dependency",),
    )
    services.service(
        "dependency",
        lambda: _Closeable("dependency", closed),
    )

    services.close()

    assert closed == ["dependent", "dependency"]


def test_clearing_dependency_discards_realized_dependents(tmp_path: Path) -> None:
    services = RuntimeServices(_config(tmp_path))
    dependency_calls = 0
    dependent_calls = 0

    def dependency() -> object:
        nonlocal dependency_calls
        dependency_calls += 1
        return object()

    def dependent() -> tuple[object, int]:
        nonlocal dependent_calls
        dependent_calls += 1
        return (
            services.service("dependency", dependency),
            dependent_calls,
        )

    first = services.service("dependent", dependent)
    services.clear_service("dependency")
    assert services.cache_info("dependency").currsize == 0
    assert services.cache_info("dependent").currsize == 0

    second = services.service("dependent", dependent)
    assert second is not first
    assert dependency_calls == 2
    assert dependent_calls == 2
    services.close()


def test_runtime_service_cycle_fails_without_partial_instance(tmp_path: Path) -> None:
    services = RuntimeServices(_config(tmp_path))

    def first() -> object:
        return services.service("second", second)

    def second() -> object:
        return services.service("first", first)

    with pytest.raises(RuntimeServiceCycleError, match="first -> second -> first"):
        services.service("first", first)

    assert services.cache_info("first").currsize == 0
    assert services.cache_info("second").currsize == 0
    services.close()


def test_runtime_service_decorator_uses_installed_container_and_cache_adapter(
    tmp_path: Path,
) -> None:
    calls = 0
    name = "decorated-test-service"

    with _temporary_runtime_service(name):

        @runtime_service(name)
        def decorated() -> object:
            nonlocal calls
            calls += 1
            return object()

        with _isolated_process_runtime():
            services = RuntimeServices(_config(tmp_path))
            install_runtime_services(services)
            graph_before = services.service_manifest(include_state=False)
            first = decorated()
            assert decorated() is first
            assert calls == 1
            assert decorated.cache_info().currsize == 1
            assert services.service_manifest(include_state=False) == graph_before

            decorated.cache_clear()
            assert decorated.cache_info().currsize == 0
            assert decorated() is not first
            assert calls == 2


def test_two_containers_supply_isolated_named_services(tmp_path: Path) -> None:
    first = RuntimeServices(_config(tmp_path / "first"))
    second = RuntimeServices(_config(tmp_path / "second"))

    def example() -> object:
        return object()

    first_value = first.service("example", example)
    second_value = second.service("example", example)

    assert first_value is not second_value
    assert first.service_manifest(include_state=False)["service_graph_id"] == (
        second.service_manifest(include_state=False)["service_graph_id"]
    )
    first.close()
    second.close()


def test_foundational_factories_are_stable_runtime_proxies_without_module_scan() -> None:
    concurrent_nodes.install_capability()

    assert server_module.workspace is concurrent_nodes.workspace
    assert build_module.workspace is concurrent_nodes.workspace
    assert build_module.compiler_bridge is concurrent_nodes.compiler_bridge
    assert "sys.modules" not in inspect.getsource(concurrent_nodes.install_capability)
    assert "os.environ" not in inspect.getsource(server_module.workspace)
    assert "lru_cache" not in inspect.getsource(build_module.edit_batches)


def test_foundational_build_services_are_runtime_owned(tmp_path: Path) -> None:
    class _Workspace:
        def close(self) -> None:
            pass

    workspace = _Workspace()
    services = RuntimeServices(
        _config(tmp_path),
        workspace_factory=lambda _config: workspace,
    )

    with _isolated_process_runtime():
        install_runtime_services(services)
        assert build_module.edit_batches().workspace is workspace
        assert build_module.branch_activity().workspace is workspace
        assert build_module.revision_inspection().workspace is workspace
        assert build_module.revision_diffs().workspace is workspace
        assert build_module.merge_previews().workspace is workspace
        assert build_module.build_targets().workspace is workspace

        names = {
            item["name"] for item in services.service_manifest()["services"]
        }
        assert {
            "workspace",
            "edit_batches",
            "branch_activity",
            "revision_inspection",
            "revision_diffs",
            "merge_previews",
            "build_targets",
        }.issubset(names)


def test_runtime_identity_binds_state_free_service_graph(tmp_path: Path) -> None:
    class _Identity:
        @staticmethod
        def report() -> dict[str, str]:
            return {"format": "test-runtime", "runtime_id": "old"}

    with _isolated_process_runtime():
        services = RuntimeServices(_config(tmp_path))
        install_runtime_services(services)
        expected = services.service_manifest(include_state=False)

        result = RuntimeIdentityWithServices(_Identity()).report()  # type: ignore[arg-type]

        assert result["service_graph"] == expected
        assert "initialized_services" not in result["service_graph"]
        assert result["runtime_id"] != "old"
        assert len(result["runtime_id"]) == 64
