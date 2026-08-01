from __future__ import annotations

from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from weave_frontend.application_runtime_binding import bind_application_runtime
from weave_frontend.context_capability_installers import (
    install_production_capability,
    production_installer_names,
)
from weave_frontend.mcp_capabilities import ApplicationContext
from weave_frontend.runtime_config import RuntimeConfig
from weave_frontend.runtime_container import RuntimeServices, runtime_services


class _Server:
    pass


def _runtime(tmp_path: Path, name: str) -> RuntimeServices:
    return RuntimeServices(
        RuntimeConfig.from_environ(
            {"WEAVE_DB_PATH": str(tmp_path / f"{name}.db")}
        )
    )


def _context(tmp_path: Path, name: str) -> ApplicationContext:
    return ApplicationContext(
        server=_Server(),
        runtime=_runtime(tmp_path, name),
    )


def _materialize(runtime: RuntimeServices, *names: str) -> None:
    for name in names:
        runtime.service(
            name,
            lambda name=name: SimpleNamespace(name=name),
            origin=f"tests.{name}",
        )


def test_production_installer_table_covers_every_historical_hook() -> None:
    assert production_installer_names() == (
        "artifact_storage",
        "concurrent_nodes",
        "database_backup",
        "merge_candidate_test_execution",
        "merge_test_impact",
        "revert",
        "runtime_identity",
        "test_targets",
        "tested_merge_attestations",
    )


def test_production_installer_requires_application_runtime_binding(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, "unbound")
    module = ModuleType("weave_frontend.mcp_revert")

    with pytest.raises(RuntimeError, match="application runtime binding"):
        install_production_capability("revert", module, context)


def test_simple_production_installer_clears_only_context_runtime(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, "application")
    other = _runtime(tmp_path, "other")
    _materialize(context.runtime, "reverts")
    _materialize(other, "reverts")

    module = ModuleType("weave_frontend.mcp_revert")

    def legacy_installer() -> None:
        raise AssertionError("module-local production hook must not be invoked")

    module.install_capability = legacy_installer  # type: ignore[attr-defined]

    with bind_application_runtime(context.runtime):
        assert install_production_capability("revert", module, context)

    assert not context.runtime.service_initialized("reverts")
    assert other.service_initialized("reverts")


def test_merge_candidate_installer_restores_metadata_and_clears_services(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, "merge-candidate")
    names = (
        "merge_candidate_test_batches",
        "merge_candidate_build_inspection",
        "merge_candidate_builds",
    )
    _materialize(context.runtime, *names)
    observed: list[RuntimeServices] = []
    module = ModuleType("weave_frontend.mcp_merge_candidate_test_runs")
    module.install_metadata_aware_merge_services = (  # type: ignore[attr-defined]
        lambda: observed.append(runtime_services())
    )

    with bind_application_runtime(context.runtime):
        assert install_production_capability(
            "merge_candidate_test_execution",
            module,
            context,
        )

    assert observed == [context.runtime]
    assert all(not context.runtime.service_initialized(name) for name in names)


def test_artifact_installer_rebuilds_quota_on_context_runtime(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, "artifact")
    _materialize(context.runtime, "artifact_quota", "artifact_storage")
    observed: list[RuntimeServices] = []
    module = ModuleType("weave_frontend.mcp_artifact_storage")
    module.artifact_quota = (  # type: ignore[attr-defined]
        lambda: observed.append(runtime_services())
    )

    with bind_application_runtime(context.runtime):
        assert install_production_capability(
            "artifact_storage",
            module,
            context,
        )

    assert observed == [context.runtime]
    assert not context.runtime.service_initialized("artifact_quota")
    assert not context.runtime.service_initialized("artifact_storage")


def test_module_identity_is_required_for_production_dispatch(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, "custom")

    with bind_application_runtime(context.runtime):
        assert not install_production_capability(
            "revert",
            ModuleType("example.custom_revert"),
            context,
        )
        assert not install_production_capability(
            "custom",
            ModuleType("weave_frontend.mcp_revert"),
            context,
        )
