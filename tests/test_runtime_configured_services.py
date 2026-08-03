from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

import weave_frontend.mcp_artifact_storage as artifact_storage_module
import weave_frontend.mcp_build as build_module
import weave_frontend.mcp_concurrent_nodes as concurrent_nodes
import weave_frontend.mcp_database_backup as backup_module
import weave_frontend.mcp_merge_candidate_test_runs as candidate_module
import weave_frontend.mcp_runtime_identity as runtime_identity_module
import weave_frontend.mcp_test_batches as batch_module
import weave_frontend.mcp_test_runs as run_module
import weave_frontend.mcp_test_targets as target_module
import weave_frontend.mcp_tested_merge_attestations as attestation_module
import weave_frontend.runtime_config as runtime_config_module
import weave_frontend.runtime_container as runtime_module
from weave_frontend.runtime_container import (
    close_runtime_services,
    runtime_config,
)
from weave_frontend.runtime_sandbox import RuntimeBubblewrapSandbox


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


def _clear_dependent_services() -> None:
    runtime_identity_module.runtime_identities.cache_clear()
    artifact_storage_module.artifact_quota.cache_clear()
    artifact_storage_module.artifact_storage.cache_clear()
    attestation_module.tested_merge_attestations.cache_clear()
    candidate_module.merge_candidate_test_batches.cache_clear()
    candidate_module.merge_candidate_build_inspection.cache_clear()
    candidate_module.merge_candidate_builds.cache_clear()
    batch_module.test_batches.cache_clear()
    run_module.test_runs.cache_clear()
    target_module.test_target_pages.cache_clear()
    target_module.test_targets.cache_clear()
    for factory in (
        build_module.build_target_validator,
        build_module.merge_validation_sets,
        build_module.merge_validations,
        build_module.merge_impacts,
        build_module.build_targets,
        build_module.build_inspection,
        build_module.merge_previews,
    ):
        factory.cache_clear()
    backup_module.database_backups.cache_clear()


def test_production_service_roots_and_sandbox_use_one_startup_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    executables = {
        name: tools / name for name in ("weavec", "bwrap", "prlimit")
    }
    for path in executables.values():
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)

    roots = {
        "WEAVE_BUILD_ROOT": tmp_path / "builds",
        "WEAVE_DATABASE_BACKUP_ROOT": tmp_path / "backups",
        "WEAVE_MERGE_ATTESTATION_ROOT": tmp_path / "attestations",
        "WEAVE_MERGE_BUILD_ROOT": tmp_path / "candidate-builds",
        "WEAVE_MERGE_TEST_RUN_ROOT": tmp_path / "qualifications",
        "WEAVE_TEST_BATCH_ROOT": tmp_path / "batches",
        "WEAVE_TEST_RUN_ROOT": tmp_path / "runs",
    }

    def which(name: str) -> str | None:
        path = executables.get(name)
        return None if path is None else str(path)

    with _isolated_process_runtime():
        _clear_dependent_services()
        monkeypatch.setattr(runtime_config_module.shutil, "which", which)
        monkeypatch.setenv("WEAVE_DB_PATH", str(tmp_path / "runtime.db"))
        for name, path in roots.items():
            monkeypatch.setenv(name, str(path))
        startup = runtime_config()

        for name in roots:
            monkeypatch.setenv(name, str(tmp_path / "changed" / name.lower()))
        monkeypatch.setenv("WEAVEC_BIN", str(tmp_path / "changed-weavec"))
        monkeypatch.setenv("WEAVE_BWRAP", str(tmp_path / "changed-bwrap"))

        try:
            committed = concurrent_nodes.compiler_bridge()
            runs = run_module.test_runs()
            batches = batch_module.test_batches()
            candidate_builds = candidate_module.merge_candidate_builds()
            candidate_runs = candidate_module.merge_candidate_test_batches()
            attestations = attestation_module.tested_merge_attestations()
            backups = backup_module.database_backups()

            assert committed.build_root == roots["WEAVE_BUILD_ROOT"].resolve()
            assert committed._configured_compiler == str(
                executables["weavec"].resolve()
            )
            assert runs.run_root == roots["WEAVE_TEST_RUN_ROOT"].resolve()
            assert batches.batch_root == roots["WEAVE_TEST_BATCH_ROOT"].resolve()
            assert candidate_builds.build_root == roots[
                "WEAVE_MERGE_BUILD_ROOT"
            ].resolve()
            assert candidate_runs.run_root == roots[
                "WEAVE_MERGE_TEST_RUN_ROOT"
            ].resolve()
            assert attestations.attestation_root == roots[
                "WEAVE_MERGE_ATTESTATION_ROOT"
            ].resolve()
            assert backups.backup_root == roots[
                "WEAVE_DATABASE_BACKUP_ROOT"
            ].resolve()
            assert isinstance(runs.sandbox, RuntimeBubblewrapSandbox)
            assert isinstance(candidate_runs.sandbox, RuntimeBubblewrapSandbox)
            assert runs.sandbox.executable == executables["bwrap"].resolve()
            assert runs.sandbox.prlimit == executables["prlimit"].resolve()
            assert candidate_runs.sandbox.executable == (
                executables["bwrap"].resolve()
            )
            assert startup is runtime_config()
        finally:
            _clear_dependent_services()
