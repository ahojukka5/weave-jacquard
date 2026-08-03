from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

import weave_frontend.mcp_artifact_storage as artifact_module
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
            "WEAVE_ARTIFACT_MAX_BYTES": "1234",
        }
    )


def test_artifact_services_are_runtime_owned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots = {
        "committed_builds": tmp_path / "committed-builds",
        "candidate_builds": tmp_path / "candidate-builds",
        "test_runs": tmp_path / "test-runs",
        "test_batches": tmp_path / "test-batches",
        "candidate_test_qualifications": tmp_path / "candidate-tests",
        "tested_merge_attestations": tmp_path / "attestations",
        "database_backups": tmp_path / "database-backups",
    }

    def verifier(family: str):
        return lambda artifact_id: {
            "family": family,
            "artifact_id": artifact_id,
        }

    workspace = SimpleNamespace(db=SimpleNamespace(path=tmp_path / "runtime.db"))
    compiler = SimpleNamespace(
        build_root=roots["committed_builds"],
        get=verifier("committed_builds"),
    )
    candidate_builds = SimpleNamespace(
        build_root=roots["candidate_builds"],
        get=verifier("candidate_builds"),
    )
    runs = SimpleNamespace(
        run_root=roots["test_runs"],
        get=verifier("test_runs"),
    )
    batches = SimpleNamespace(
        batch_root=roots["test_batches"],
        get=verifier("test_batches"),
    )
    candidate_tests = SimpleNamespace(
        run_root=roots["candidate_test_qualifications"],
        get=verifier("candidate_test_qualifications"),
    )
    attestations = SimpleNamespace(
        attestation_root=roots["tested_merge_attestations"],
        get=verifier("tested_merge_attestations"),
    )
    backups = SimpleNamespace(
        backup_root=roots["database_backups"],
        get=verifier("database_backups"),
    )
    publishers = (
        compiler,
        candidate_builds,
        runs,
        batches,
        candidate_tests,
        attestations,
        backups,
    )

    monkeypatch.setattr(artifact_module, "workspace", lambda: workspace)
    monkeypatch.setattr(artifact_module, "compiler_bridge", lambda: compiler)
    monkeypatch.setattr(
        artifact_module,
        "merge_candidate_builds",
        lambda: candidate_builds,
    )
    monkeypatch.setattr(artifact_module, "test_runs", lambda: runs)
    monkeypatch.setattr(artifact_module, "test_batches", lambda: batches)
    monkeypatch.setattr(
        artifact_module,
        "merge_candidate_test_batches",
        lambda: candidate_tests,
    )
    monkeypatch.setattr(
        artifact_module,
        "tested_merge_attestations",
        lambda: attestations,
    )
    monkeypatch.setattr(artifact_module, "database_backups", lambda: backups)
    monkeypatch.setattr(
        artifact_module,
        "install_quota_aware_compiler_bridge",
        lambda bridge: bridge,
    )

    runtime = RuntimeServices(
        _config(tmp_path),
        workspace_factory=lambda _config: workspace,
        compiler_bridge_factory=lambda _workspace, _config: compiler,
    )

    with _isolated_process_runtime():
        install_runtime_services(runtime)

        storage = artifact_module.artifact_storage()
        inventory = artifact_module.artifact_inventory()
        quota = artifact_module.artifact_quota()

        expected_roots = {
            name: path.resolve() for name, path in roots.items()
        }
        assert storage.roots == expected_roots
        assert {
            family.name: family.root for family in inventory.families
        } == expected_roots
        assert quota.accounting is storage
        assert quota.lock_path == (
            tmp_path / ".weave-artifact-quota.lock"
        ).resolve()
        assert quota.max_bytes == 1234
        for publisher in publishers:
            assert publisher.artifact_quota is quota

        entries = {
            item["name"]: item
            for item in runtime.service_manifest()["services"]
        }
        expected_dependencies = [
            "compiler_bridge",
            "database_backups",
            "merge_candidate_builds",
            "merge_candidate_test_batches",
            "test_batches",
            "test_runs",
            "tested_merge_attestations",
        ]
        assert entries["artifact_storage"]["depends_on"] == expected_dependencies
        assert entries["artifact_inventory"]["depends_on"] == expected_dependencies
        assert entries["artifact_quota"]["depends_on"] == [
            "artifact_storage",
            "compiler_bridge",
            "database_backups",
            "merge_candidate_builds",
            "merge_candidate_test_batches",
            "test_batches",
            "test_runs",
            "tested_merge_attestations",
            "workspace",
        ]

        runtime.clear_service("database_backups")

        assert artifact_module.artifact_storage.cache_info().currsize == 0
        assert artifact_module.artifact_inventory.cache_info().currsize == 0
        assert artifact_module.artifact_quota.cache_info().currsize == 0
