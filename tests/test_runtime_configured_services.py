from __future__ import annotations

from pathlib import Path

import pytest

import weave_frontend.mcp_concurrent_nodes as concurrent_nodes
import weave_frontend.mcp_database_backup as backup_module
import weave_frontend.mcp_merge_candidate_test_runs as candidate_module
import weave_frontend.mcp_test_batches as batch_module
import weave_frontend.mcp_test_runs as run_module
import weave_frontend.mcp_tested_merge_attestations as attestation_module
import weave_frontend.runtime_config as runtime_config_module
from weave_frontend.application_runtime_binding import bind_application_runtime
from weave_frontend.runtime_config import RuntimeConfig
from weave_frontend.runtime_container import (
    RuntimeServices,
    runtime_config,
    runtime_services,
)
from weave_frontend.runtime_sandbox import RuntimeBubblewrapSandbox


def test_production_service_roots_and_sandbox_use_one_startup_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    executables = {name: tools / name for name in ("weavec", "bwrap", "prlimit")}
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

    monkeypatch.setattr(runtime_config_module.shutil, "which", which)
    environ = {
        "WEAVE_DB_PATH": str(tmp_path / "runtime.db"),
        **{name: str(path) for name, path in roots.items()},
    }
    startup = RuntimeConfig.from_environ(environ)
    runtime = RuntimeServices(startup)
    process_runtime = runtime_services()
    process_state = process_runtime.service_manifest()["initialized_services"]

    for name in roots:
        environ[name] = str(tmp_path / "changed" / name.lower())
    environ["WEAVE_DB_PATH"] = str(tmp_path / "changed-runtime.db")
    executables.update(
        {
            "weavec": tmp_path / "changed-weavec",
            "bwrap": tmp_path / "changed-bwrap",
            "prlimit": tmp_path / "changed-prlimit",
        }
    )

    try:
        with bind_application_runtime(runtime):
            committed = concurrent_nodes.compiler_bridge()
            runs = run_module.test_runs()
            batches = batch_module.test_batches()
            candidate_builds = candidate_module.merge_candidate_builds()
            candidate_runs = candidate_module.merge_candidate_test_batches()
            attestations = attestation_module.tested_merge_attestations()
            backups = backup_module.database_backups()

            assert committed.build_root == roots["WEAVE_BUILD_ROOT"].resolve()
            assert committed._configured_compiler == str((tools / "weavec").resolve())
            assert runs.run_root == roots["WEAVE_TEST_RUN_ROOT"].resolve()
            assert batches.batch_root == roots["WEAVE_TEST_BATCH_ROOT"].resolve()
            assert candidate_builds.build_root == roots["WEAVE_MERGE_BUILD_ROOT"].resolve()
            assert candidate_runs.run_root == roots["WEAVE_MERGE_TEST_RUN_ROOT"].resolve()
            assert attestations.attestation_root == roots["WEAVE_MERGE_ATTESTATION_ROOT"].resolve()
            assert backups.backup_root == roots["WEAVE_DATABASE_BACKUP_ROOT"].resolve()
            assert isinstance(runs.sandbox, RuntimeBubblewrapSandbox)
            assert isinstance(candidate_runs.sandbox, RuntimeBubblewrapSandbox)
            assert runs.sandbox.executable == (tools / "bwrap").resolve()
            assert runs.sandbox.prlimit == (tools / "prlimit").resolve()
            assert candidate_runs.sandbox.executable == (tools / "bwrap").resolve()
            assert startup is runtime_config()
            assert runtime_config().database_path == (tmp_path / "runtime.db").resolve()
    finally:
        runtime.close()

    assert process_runtime.service_manifest()["initialized_services"] == (process_state)
