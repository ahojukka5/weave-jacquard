from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

import weave_frontend.mcp_project_merge_impact_queue as impact_module
import weave_frontend.mcp_project_merge_queue as queue_module
import weave_frontend.mcp_selected_merge_preflight_batch as preflight_module
import weave_frontend.mcp_selected_merge_train_preview as train_module
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
        {"WEAVE_DB_PATH": str(tmp_path / "runtime.db")}
    )


def test_project_merge_workflows_are_runtime_owned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = SimpleNamespace()
    previews = SimpleNamespace(workspace=workspace)
    statuses = SimpleNamespace()
    impacts = SimpleNamespace()
    policies = SimpleNamespace()
    preflights = SimpleNamespace()

    monkeypatch.setattr(queue_module, "merge_previews", lambda: previews)
    monkeypatch.setattr(
        queue_module,
        "project_agent_statuses",
        lambda: statuses,
    )
    monkeypatch.setattr(
        impact_module,
        "project_merge_queues",
        queue_module.project_merge_queues,
    )
    monkeypatch.setattr(impact_module, "merge_impacts", lambda: impacts)
    monkeypatch.setattr(impact_module, "merge_policies", lambda: policies)
    monkeypatch.setattr(
        train_module,
        "project_merge_queues",
        queue_module.project_merge_queues,
    )
    monkeypatch.setattr(
        preflight_module,
        "project_merge_queues",
        queue_module.project_merge_queues,
    )
    monkeypatch.setattr(
        preflight_module,
        "merge_preflights",
        lambda: preflights,
    )

    runtime = RuntimeServices(
        _config(tmp_path),
        workspace_factory=lambda _config: workspace,
        compiler_bridge_factory=lambda _workspace, _config: SimpleNamespace(),
    )

    with _isolated_process_runtime():
        install_runtime_services(runtime)

        queues = queue_module.project_merge_queues()
        impact_queues = impact_module.project_merge_impact_queues()
        train_previews = train_module.selected_merge_train_previews()
        preflight_batches = preflight_module.selected_merge_preflight_batches()

        assert queues.previews is previews
        assert queues.statuses is statuses
        assert queues.workspace is workspace
        assert impact_queues.queues is queues
        assert impact_queues.impacts is impacts
        assert impact_queues.policies is policies
        assert train_previews.queues is queues
        assert train_previews.catalogs is queues.catalogs
        assert train_previews.previews is previews
        assert preflight_batches.queues is queues
        assert preflight_batches.catalogs is queues.catalogs
        assert preflight_batches.preflights is preflights

        entries = {
            item["name"]: item
            for item in runtime.service_manifest()["services"]
        }
        assert entries["project_merge_queues"]["depends_on"] == [
            "merge_previews",
            "project_agent_statuses",
        ]
        assert entries["project_merge_impact_queues"]["depends_on"] == [
            "merge_impacts",
            "merge_policies",
            "project_merge_queues",
        ]
        assert entries["selected_merge_train_previews"]["depends_on"] == [
            "project_merge_queues"
        ]
        assert entries["selected_merge_preflight_batches"]["depends_on"] == [
            "merge_preflights",
            "project_merge_queues",
        ]

        runtime.clear_service("project_merge_queues")

        for factory in (
            queue_module.project_merge_queues,
            impact_module.project_merge_impact_queues,
            train_module.selected_merge_train_previews,
            preflight_module.selected_merge_preflight_batches,
        ):
            assert factory.cache_info().currsize == 0
