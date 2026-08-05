from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

import weave_frontend.application as application_module
import weave_frontend.mcp_build as build_module
import weave_frontend.mcp_concurrent_nodes as concurrent_nodes
import weave_frontend.mcp_server as server_module
import weave_frontend.runtime_config as runtime_config_module
import weave_frontend.runtime_container as runtime_module
from weave_frontend.compiler import WeavecValidator
from weave_frontend.concurrent_workspace import SExpressionWorkspace
from weave_frontend.errors import ValidationError
from weave_frontend.quota_aware_compiler_bridge import CompilerBridge
from weave_frontend.runtime_config import (
    PUBLIC_CONFIGURATION_VARIABLES,
    RuntimeConfig,
)
from weave_frontend.runtime_container import (
    RuntimeClosedError,
    RuntimeServices,
    close_runtime_services,
    install_runtime_services,
    reset_runtime_services,
    runtime_config,
    runtime_services,
)
from weave_frontend.runtime_sandbox import RuntimeBubblewrapSandbox


class _Workspace:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class _Bridge:
    def __init__(self, workspace: Any, sequence: int) -> None:
        self.workspace = workspace
        self.sequence = sequence


def _config(tmp_path: Path, **values: str) -> RuntimeConfig:
    environ = {"WEAVE_DB_PATH": str(tmp_path / "runtime.db"), **values}
    return RuntimeConfig.from_environ(environ)


def _disable_compiler_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        runtime_config_module.RuntimeConfig,
        "_discover_weavec",
        staticmethod(lambda _source_root: None),
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


def test_runtime_config_is_canonical_immutable_snapshot(tmp_path: Path) -> None:
    source = {
        "WEAVE_DB_PATH": str(tmp_path / "workspace.db"),
        "WEAVEC_BIN": "/opt/weavec",
        "WEAVEC_SOURCE_ROOT": "/src/weavec",
        "WEAVE_ARTIFACT_MAX_BYTES": "4096",
        "WEAVE_BUILD_ROOT": "/artifacts/builds",
        "WEAVE_BWRAP": "/usr/bin/bwrap",
        "WEAVE_DATABASE_BACKUP_ROOT": "/artifacts/backups",
        "WEAVE_MERGE_ATTESTATION_ROOT": "/artifacts/attestations",
        "WEAVE_MERGE_BUILD_ROOT": "/artifacts/candidates",
        "WEAVE_MERGE_TEST_RUN_ROOT": "/artifacts/qualifications",
        "WEAVE_TEST_BATCH_ROOT": "/artifacts/batches",
        "WEAVE_TEST_RUN_ROOT": "/artifacts/runs",
    }

    config = RuntimeConfig.from_environ(source)
    source["WEAVE_DB_PATH"] = "/changed-after-startup.db"

    assert tuple(
        sorted(PUBLIC_CONFIGURATION_VARIABLES)
    ) == PUBLIC_CONFIGURATION_VARIABLES
    assert config.configuration_variables == PUBLIC_CONFIGURATION_VARIABLES
    assert config.database_path == tmp_path / "workspace.db"
    assert config.artifact_max_bytes == 4096
    assert config.build_root == Path("/artifacts/builds")
    assert config.database_backup_root == Path("/artifacts/backups")
    assert config.merge_attestation_root == Path("/artifacts/attestations")
    assert config.merge_build_root == Path("/artifacts/candidates")
    assert config.merge_test_run_root == Path("/artifacts/qualifications")
    assert config.test_batch_root == Path("/artifacts/batches")
    assert config.test_run_root == Path("/artifacts/runs")
    assert config.configured_variables == PUBLIC_CONFIGURATION_VARIABLES
    assert config.configured_environment["WEAVE_DB_PATH"] == str(
        tmp_path / "workspace.db"
    )
    with pytest.raises(TypeError):
        cast(dict[str, str], config.configured_environment)["WEAVE_DB_PATH"] = "x"


def test_runtime_config_freezes_explicit_defaults_when_values_are_unset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_compiler_discovery(monkeypatch)
    monkeypatch.setattr(runtime_config_module.shutil, "which", lambda _name: None)
    config = _config(
        tmp_path,
        WEAVEC_BIN="",
        WEAVE_ARTIFACT_MAX_BYTES="",
        WEAVE_BUILD_ROOT="",
    )

    assert config.weavec_binary is None
    assert config.artifact_max_bytes is None
    assert config.build_root == tmp_path / ".weave-build"
    assert config.database_backup_root == tmp_path / ".weave-database-backups"
    assert config.merge_build_root == tmp_path / ".weave-build" / "merge-candidates"
    assert config.test_run_root == tmp_path / ".weave-test-runs"
    assert config.test_batch_root == tmp_path / ".weave-test-runs" / "batches"
    assert config.bubblewrap_binary is None
    assert config.prlimit_binary is None
    assert config.configured_variables == ("WEAVE_DB_PATH",)


def test_runtime_config_rejects_invalid_quota(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsigned decimal"):
        _config(tmp_path, WEAVE_ARTIFACT_MAX_BYTES=" 10")


def test_runtime_services_are_lazy_shared_and_resettable(tmp_path: Path) -> None:
    workspaces: list[_Workspace] = []
    bridges: list[_Bridge] = []

    def make_workspace(_runtime_config: RuntimeConfig) -> _Workspace:
        value = _Workspace()
        workspaces.append(value)
        return value

    def make_bridge(workspace: Any, _runtime_config: RuntimeConfig) -> _Bridge:
        value = _Bridge(workspace, len(bridges) + 1)
        bridges.append(value)
        return value

    services = RuntimeServices(
        _config(tmp_path),
        workspace_factory=make_workspace,
        compiler_bridge_factory=make_bridge,
    )

    assert not services.workspace_initialized
    assert not services.compiler_bridge_initialized
    workspace = services.workspace()
    assert services.workspace() is workspace
    first = services.compiler_bridge()
    assert services.compiler_bridge() is first
    assert first.workspace is workspace
    assert len(workspaces) == 1
    assert len(bridges) == 1

    services.clear_compiler_bridge()
    second = services.compiler_bridge()
    assert second is not first
    assert second.workspace is workspace
    assert second.sequence == 2

    services.close()
    services.close()
    assert workspace.close_calls == 1
    with pytest.raises(RuntimeClosedError):
        services.workspace()
    with pytest.raises(RuntimeClosedError):
        services.compiler_bridge()


def test_installing_runtime_closes_previous_container(tmp_path: Path) -> None:
    first_workspace = _Workspace()
    second_workspace = _Workspace()
    first = RuntimeServices(
        _config(tmp_path / "first"),
        workspace_factory=lambda _config: first_workspace,
    )
    second = RuntimeServices(
        _config(tmp_path / "second"),
        workspace_factory=lambda _config: second_workspace,
    )

    with _isolated_process_runtime():
        install_runtime_services(first)
        assert runtime_services().workspace() is first_workspace
        install_runtime_services(second)
        assert first.closed
        assert first_workspace.close_calls == 1
        assert runtime_services().workspace() is second_workspace

    assert second.closed
    assert second_workspace.close_calls == 1


def test_process_runtime_freezes_environment_until_reset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_process_runtime():
        monkeypatch.setenv("WEAVE_DB_PATH", str(tmp_path / "first.db"))
        first = runtime_config()
        monkeypatch.setenv("WEAVE_DB_PATH", str(tmp_path / "second.db"))

        assert runtime_config() is first
        assert runtime_config().database_path == tmp_path / "first.db"

        reset_runtime_services()
        assert runtime_config().database_path == tmp_path / "second.db"


def test_foundational_capability_exports_runtime_backed_production_factories() -> None:
    assert server_module.workspace is concurrent_nodes.workspace
    assert build_module.workspace is concurrent_nodes.workspace
    assert build_module.compiler_bridge is concurrent_nodes.compiler_bridge
    assert application_module.PUBLIC_CONFIGURATION_VARIABLES == (
        PUBLIC_CONFIGURATION_VARIABLES
    )


def test_production_runtime_owns_race_safe_workspace_and_quota_bridge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiler = tmp_path / "weavec-startup"
    compiler.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    compiler.chmod(0o755)

    with _isolated_process_runtime():
        monkeypatch.setenv("WEAVE_DB_PATH", str(tmp_path / "production.db"))
        monkeypatch.setenv("WEAVE_BUILD_ROOT", str(tmp_path / "builds"))
        monkeypatch.setenv("WEAVEC_BIN", str(compiler))
        workspace = concurrent_nodes.workspace()
        bridge = concurrent_nodes.compiler_bridge()

        assert isinstance(workspace, SExpressionWorkspace)
        assert type(bridge) is CompilerBridge
        assert bridge.workspace is workspace
        assert bridge.build_root == (tmp_path / "builds").resolve()
        assert bridge._configured_compiler == str(compiler)
        assert bridge._environment_fallback is False
        assert workspace.validator.binary == compiler.resolve()
        assert workspace.validator.environment_fallback is False
        assert concurrent_nodes.workspace.cache_info().currsize == 1
        assert concurrent_nodes.compiler_bridge.cache_info().currsize == 1

        close_runtime_services()
        assert concurrent_nodes.workspace.cache_info().currsize == 0
        assert concurrent_nodes.compiler_bridge.cache_info().currsize == 0


def test_unset_compiler_and_sandbox_do_not_adopt_later_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    later_compiler = tmp_path / "weavec-later"
    later_bwrap = tmp_path / "bwrap-later"
    for executable in (later_compiler, later_bwrap):
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)

    _disable_compiler_discovery(monkeypatch)
    monkeypatch.setattr(runtime_config_module.shutil, "which", lambda _name: None)
    config = _config(tmp_path)
    monkeypatch.setenv("WEAVEC_BIN", str(later_compiler))
    monkeypatch.setenv("WEAVE_BWRAP", str(later_bwrap))
    services = RuntimeServices(config)

    try:
        workspace = services.workspace()
        bridge = services.compiler_bridge()
        sandbox = RuntimeBubblewrapSandbox.from_config(config)

        assert workspace.validator.binary is None
        assert sandbox.executable is None
        assert sandbox.prlimit is None
        with pytest.raises(ValidationError) as captured:
            bridge._compiler_path()
        assert captured.value.code == "WEAVEC_NOT_FOUND"
    finally:
        services.close()


def test_runtime_sandbox_paths_are_frozen_and_resolved(tmp_path: Path) -> None:
    bwrap = tmp_path / "tools" / "bwrap"
    prlimit = tmp_path / "tools" / "prlimit"
    config = RuntimeConfig.from_environ(
        {
            "WEAVE_DB_PATH": str(tmp_path / "runtime.db"),
            "WEAVE_BWRAP": str(bwrap),
        }
    )
    config = replace(config, prlimit_binary=str(prlimit))

    sandbox = RuntimeBubblewrapSandbox.from_config(config)

    assert sandbox.executable == bwrap.resolve()
    assert sandbox.prlimit == prlimit.resolve()


def test_snapshot_validator_recovers_configured_binary_after_transient_absence(
    tmp_path: Path,
) -> None:
    compiler = tmp_path / "weavec"
    compiler.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    compiler.chmod(0o755)
    validator = WeavecValidator(compiler, environment_fallback=False)
    assert validator.binary == compiler.resolve()

    compiler.unlink()
    assert validator._active_binary() is None

    compiler.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    compiler.chmod(0o755)
    assert validator._active_binary() == compiler.resolve()
