from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import weave_frontend.mcp_build as build_module
import weave_frontend.mcp_build_discovery as build_discovery_module
import weave_frontend.mcp_database_backup as backup_module
import weave_frontend.mcp_revert as revert_module
import weave_frontend.mcp_revision_reads as revision_reads_module
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
            "WEAVE_DATABASE_BACKUP_ROOT": str(tmp_path / "backups"),
        }
    )


def test_read_and_recovery_services_are_runtime_owned(tmp_path: Path) -> None:
    workspace = SimpleNamespace(db=object())
    compiler_bridge = SimpleNamespace()
    services = RuntimeServices(
        _config(tmp_path),
        workspace_factory=lambda _config: workspace,
        compiler_bridge_factory=lambda _workspace, _config: compiler_bridge,
    )

    with _isolated_process_runtime():
        install_runtime_services(services)

        revision_reads = revision_reads_module.revision_reads()
        reverts = revert_module.reverts()
        build_discovery = build_discovery_module.build_discovery()
        database_backups = backup_module.database_backups()

        assert revision_reads.workspace is workspace
        assert reverts.workspace is workspace
        assert reverts.previews is build_module.merge_previews()
        assert build_discovery.bridge is compiler_bridge
        assert database_backups.database is workspace.db

        entries = {item["name"]: item for item in services.service_manifest()["services"]}
        assert entries["revision_reads"]["depends_on"] == ["workspace"]
        assert entries["reverts"]["depends_on"] == [
            "merge_previews",
            "workspace",
        ]
        assert entries["build_discovery"]["depends_on"] == ["compiler_bridge"]
        assert entries["database_backups"]["depends_on"] == ["workspace"]

        services.clear_service("workspace")

        for factory in (
            revision_reads_module.revision_reads,
            revert_module.reverts,
            build_discovery_module.build_discovery,
            backup_module.database_backups,
        ):
            assert factory.cache_info().currsize == 0
