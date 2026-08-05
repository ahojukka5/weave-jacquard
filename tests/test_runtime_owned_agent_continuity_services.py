from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import weave_frontend.mcp_agent_checkpoint as checkpoint_module
import weave_frontend.mcp_agent_checkpoint_timeline as timeline_module
import weave_frontend.mcp_build as build_module
import weave_frontend.mcp_project_agent_status as status_module
import weave_frontend.mcp_task_contracts as task_module
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
    return RuntimeConfig.from_environ({"WEAVE_DB_PATH": str(tmp_path / "runtime.db")})


def test_agent_continuity_services_are_runtime_owned(tmp_path: Path) -> None:
    workspace = SimpleNamespace()
    services = RuntimeServices(
        _config(tmp_path),
        workspace_factory=lambda _config: workspace,
    )

    with _isolated_process_runtime():
        install_runtime_services(services)

        contracts = task_module.task_contracts()
        scoped_batches = task_module.task_scoped_batches()
        checkpoints = checkpoint_module.agent_checkpoints()
        timelines = timeline_module.checkpoint_timelines()
        statuses = status_module.project_agent_statuses()

        assert contracts.workspace is workspace
        assert scoped_batches.registry is contracts
        assert scoped_batches.batches is build_module.edit_batches()
        assert checkpoints.workspace is workspace
        assert timelines.registry is checkpoints
        assert statuses.checkpoints is checkpoints

        entries = {item["name"]: item for item in services.service_manifest()["services"]}
        assert entries["task_contracts"]["depends_on"] == ["workspace"]
        assert entries["task_scoped_batches"]["depends_on"] == [
            "edit_batches",
            "task_contracts",
        ]
        assert entries["agent_checkpoints"]["depends_on"] == ["workspace"]
        assert entries["checkpoint_timelines"]["depends_on"] == ["agent_checkpoints"]
        assert entries["project_agent_statuses"]["depends_on"] == ["agent_checkpoints"]

        services.clear_service("workspace")

        for factory in (
            task_module.task_contracts,
            task_module.task_scoped_batches,
            checkpoint_module.agent_checkpoints,
            timeline_module.checkpoint_timelines,
            status_module.project_agent_statuses,
        ):
            assert factory.cache_info().currsize == 0
