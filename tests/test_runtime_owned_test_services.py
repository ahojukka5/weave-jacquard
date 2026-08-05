from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import weave_frontend.mcp_build as build_module
import weave_frontend.mcp_test_batches as batch_module
import weave_frontend.mcp_test_impact as impact_module
import weave_frontend.mcp_test_runs as run_module
import weave_frontend.mcp_test_targets as target_module
import weave_frontend.runtime_container as runtime_module
from weave_frontend.runtime_config import RuntimeConfig
from weave_frontend.runtime_container import (
    RuntimeServices,
    close_runtime_services,
    install_runtime_services,
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


def _config(tmp_path: Path) -> RuntimeConfig:
    return RuntimeConfig.from_environ(
        {
            "WEAVE_DB_PATH": str(tmp_path / "runtime.db"),
            "WEAVE_TEST_RUN_ROOT": str(tmp_path / "runs"),
            "WEAVE_TEST_BATCH_ROOT": str(tmp_path / "batches"),
        }
    )


def test_committed_test_services_are_runtime_owned(tmp_path: Path) -> None:
    workspace = SimpleNamespace(db=SimpleNamespace(path=tmp_path / "runtime.db"))
    compiler_bridge = SimpleNamespace()
    services = RuntimeServices(
        _config(tmp_path),
        workspace_factory=lambda _config: workspace,
        compiler_bridge_factory=lambda _workspace, _config: compiler_bridge,
    )

    with _isolated_process_runtime():
        install_runtime_services(services)

        targets = target_module.test_targets()
        pages = target_module.test_target_pages()
        runs = run_module.test_runs()
        batches = batch_module.test_batches()
        impacts = impact_module.test_impact_plans()

        assert targets.workspace is workspace
        assert pages.registry is targets
        assert runs.workspace is workspace
        assert runs.build_targets is build_module.build_targets()
        assert runs.tests is targets
        assert runs.compiler is compiler_bridge
        assert batches.workspace is workspace
        assert batches.tests is targets
        assert batches.runs is runs
        assert impacts.workspace is workspace
        assert impacts.build_targets is build_module.build_targets()
        assert impacts.tests is targets

        entries = {item["name"]: item for item in services.service_manifest()["services"]}
        assert entries["test_targets"]["depends_on"] == ["workspace"]
        assert entries["test_target_pages"]["depends_on"] == ["test_targets"]
        assert entries["test_runs"]["depends_on"] == [
            "build_targets",
            "compiler_bridge",
            "test_targets",
            "workspace",
        ]
        assert entries["test_batches"]["depends_on"] == [
            "test_runs",
            "test_targets",
            "workspace",
        ]
        assert entries["test_impact_plans"]["depends_on"] == [
            "build_targets",
            "test_targets",
            "workspace",
        ]

        services.clear_service("workspace")

        for factory in (
            target_module.test_targets,
            target_module.test_target_pages,
            run_module.test_runs,
            batch_module.test_batches,
            impact_module.test_impact_plans,
        ):
            assert factory.cache_info().currsize == 0
