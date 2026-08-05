from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import weave_frontend.mcp_agent_checkpoint as checkpoint_module
import weave_frontend.mcp_build as build_module
import weave_frontend.mcp_preflight as preflight_module
import weave_frontend.mcp_resume_snapshot as resume_module
import weave_frontend.mcp_task_contracts as task_module
import weave_frontend.mcp_test_targets as test_target_module
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


def test_preflight_and_resume_services_are_runtime_owned(tmp_path: Path) -> None:
    workspace = SimpleNamespace()
    services = RuntimeServices(
        _config(tmp_path),
        workspace_factory=lambda _config: workspace,
    )

    with _isolated_process_runtime():
        install_runtime_services(services)

        policies = preflight_module.merge_policies()
        preflights = preflight_module.merge_preflights()
        snapshots = resume_module.resume_snapshots()

        assert policies.workspace is workspace
        assert preflights.impacts is build_module.merge_impacts()
        assert preflights.validation_sets is build_module.merge_validation_sets()
        assert preflights.policies is policies
        assert snapshots.workspace is workspace
        assert snapshots.targets is build_module.build_targets()
        assert snapshots.policies is policies
        assert snapshots.checkpoints is checkpoint_module.agent_checkpoints()
        assert snapshots.tests is test_target_module.test_targets()
        assert snapshots.tasks is task_module.task_contracts()

        entries = {item["name"]: item for item in services.service_manifest()["services"]}
        assert entries["merge_policies"]["depends_on"] == ["workspace"]
        assert entries["merge_preflights"]["depends_on"] == [
            "merge_impacts",
            "merge_policies",
            "merge_validation_sets",
        ]
        assert entries["resume_snapshots"]["depends_on"] == [
            "agent_checkpoints",
            "build_targets",
            "merge_policies",
            "task_contracts",
            "test_targets",
            "workspace",
        ]

        services.clear_service("workspace")

        for factory in (
            preflight_module.merge_policies,
            preflight_module.merge_preflights,
            resume_module.resume_snapshots,
        ):
            assert factory.cache_info().currsize == 0
