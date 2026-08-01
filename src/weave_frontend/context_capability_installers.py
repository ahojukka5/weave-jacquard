"""Explicit context-only installers for production MCP capabilities."""

from __future__ import annotations

from collections.abc import Callable
from types import MappingProxyType, ModuleType
from typing import TYPE_CHECKING

from .runtime_container import runtime_services

if TYPE_CHECKING:
    from .mcp_capabilities import ApplicationContext

ContextInstaller = Callable[["ApplicationContext", ModuleType], None]
ProductionInstallerKey = tuple[str, str]


def _require_bound_runtime(context: ApplicationContext) -> None:
    if runtime_services() is not context.runtime:
        raise RuntimeError(
            "production capability installer requires the application runtime binding"
        )


def _clear_services(context: ApplicationContext, *names: str) -> None:
    _require_bound_runtime(context)
    for name in names:
        context.runtime.clear_service(name)


def _install_concurrent_nodes(
    context: ApplicationContext,
    module: ModuleType,
) -> None:
    del module
    _require_bound_runtime(context)
    context.runtime.cache_info("workspace")


def _install_test_targets(
    context: ApplicationContext,
    module: ModuleType,
) -> None:
    _require_bound_runtime(context)
    module.install_metadata_aware_merge_services()


def _install_merge_test_impact(
    context: ApplicationContext,
    module: ModuleType,
) -> None:
    _require_bound_runtime(context)
    module.install_metadata_aware_merge_services()
    context.runtime.clear_service("merge_test_impact_plans")


def _install_merge_candidate_test_execution(
    context: ApplicationContext,
    module: ModuleType,
) -> None:
    _require_bound_runtime(context)
    module.install_metadata_aware_merge_services()
    for name in (
        "merge_candidate_test_batches",
        "merge_candidate_build_inspection",
        "merge_candidate_builds",
    ):
        context.runtime.clear_service(name)


def _install_tested_merge_attestations(
    context: ApplicationContext,
    module: ModuleType,
) -> None:
    del module
    _clear_services(context, "tested_merge_attestations")


def _install_revert(
    context: ApplicationContext,
    module: ModuleType,
) -> None:
    del module
    _clear_services(context, "reverts")


def _install_database_backup(
    context: ApplicationContext,
    module: ModuleType,
) -> None:
    del module
    _clear_services(context, "database_backups")


def _install_artifact_storage(
    context: ApplicationContext,
    module: ModuleType,
) -> None:
    _clear_services(context, "artifact_quota", "artifact_storage")
    module.artifact_quota()


def _install_runtime_identity(
    context: ApplicationContext,
    module: ModuleType,
) -> None:
    del module
    _clear_services(context, "runtime_identity")


_PRODUCTION_INSTALLERS = MappingProxyType(
    {
        (
            "concurrent_nodes",
            "weave_frontend.mcp_concurrent_nodes",
        ): _install_concurrent_nodes,
        (
            "test_targets",
            "weave_frontend.mcp_test_targets",
        ): _install_test_targets,
        (
            "merge_test_impact",
            "weave_frontend.mcp_merge_test_impact",
        ): _install_merge_test_impact,
        (
            "merge_candidate_test_execution",
            "weave_frontend.mcp_merge_candidate_test_runs",
        ): _install_merge_candidate_test_execution,
        (
            "tested_merge_attestations",
            "weave_frontend.mcp_tested_merge_attestations",
        ): _install_tested_merge_attestations,
        (
            "revert",
            "weave_frontend.mcp_revert",
        ): _install_revert,
        (
            "database_backup",
            "weave_frontend.mcp_database_backup",
        ): _install_database_backup,
        (
            "artifact_storage",
            "weave_frontend.mcp_artifact_storage",
        ): _install_artifact_storage,
        (
            "runtime_identity",
            "weave_frontend.mcp_runtime_identity",
        ): _install_runtime_identity,
    }
)


def production_installer_names() -> tuple[str, ...]:
    """Return the canonical production capability names with explicit installers."""

    return tuple(sorted(name for name, _module in _PRODUCTION_INSTALLERS))


def install_production_capability(
    name: str,
    module: ModuleType,
    context: ApplicationContext,
) -> bool:
    """Install one exact production capability and report whether it was handled."""

    key: ProductionInstallerKey = (name, module.__name__)
    installer = _PRODUCTION_INSTALLERS.get(key)
    if installer is None:
        return False
    installer(context, module)
    return True


__all__ = [
    "install_production_capability",
    "production_installer_names",
]
