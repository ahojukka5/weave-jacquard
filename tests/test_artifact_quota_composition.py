from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import weave_frontend.application as application_module
import weave_frontend.mcp_artifact_storage as composition
from weave_frontend.artifact_quota import ARTIFACT_QUOTA_ENV
from weave_frontend.quota_aware_compiler_bridge import CompilerBridge


def test_quota_composition_attaches_one_guard_to_every_publisher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots = {
        "committed_builds": tmp_path / "builds",
        "candidate_builds": tmp_path / "candidate-builds",
        "test_runs": tmp_path / "runs",
        "test_batches": tmp_path / "batches",
        "candidate_test_qualifications": tmp_path / "qualifications",
        "tested_merge_attestations": tmp_path / "attestations",
        "database_backups": tmp_path / "database-backups",
    }
    for root in roots.values():
        root.mkdir()

    bridge = CompilerBridge.__new__(CompilerBridge)
    bridge.build_root = roots["committed_builds"]
    services = {
        "candidate_builds": SimpleNamespace(build_root=roots["candidate_builds"]),
        "test_runs": SimpleNamespace(run_root=roots["test_runs"]),
        "test_batches": SimpleNamespace(batch_root=roots["test_batches"]),
        "candidate_test_qualifications": SimpleNamespace(
            run_root=roots["candidate_test_qualifications"]
        ),
        "tested_merge_attestations": SimpleNamespace(
            attestation_root=roots["tested_merge_attestations"]
        ),
        "database_backups": SimpleNamespace(backup_root=roots["database_backups"]),
    }
    monkeypatch.setattr(composition, "compiler_bridge", lambda: bridge)
    monkeypatch.setattr(
        composition,
        "merge_candidate_builds",
        lambda: services["candidate_builds"],
    )
    monkeypatch.setattr(composition, "test_runs", lambda: services["test_runs"])
    monkeypatch.setattr(composition, "test_batches", lambda: services["test_batches"])
    monkeypatch.setattr(
        composition,
        "merge_candidate_test_batches",
        lambda: services["candidate_test_qualifications"],
    )
    monkeypatch.setattr(
        composition,
        "tested_merge_attestations",
        lambda: services["tested_merge_attestations"],
    )
    monkeypatch.setattr(
        composition,
        "database_backups",
        lambda: services["database_backups"],
    )
    monkeypatch.setattr(
        composition,
        "workspace",
        lambda: SimpleNamespace(db=SimpleNamespace(path=tmp_path / "weave.db")),
    )
    monkeypatch.setattr(
        composition,
        "runtime_config",
        lambda: SimpleNamespace(artifact_max_bytes=100),
    )
    composition.artifact_quota.cache_clear()
    composition.artifact_storage.cache_clear()

    try:
        quota = composition.artifact_quota()

        assert quota.max_bytes == 100
        assert bridge.artifact_quota is quota
        assert all(service.artifact_quota is quota for service in services.values())
        assert quota.accounting.roots == {name: path.resolve() for name, path in roots.items()}
    finally:
        composition.artifact_quota.cache_clear()
        composition.artifact_storage.cache_clear()


def test_quota_variable_is_declared_once_in_application_configuration() -> None:
    names = application_module.PUBLIC_CONFIGURATION_VARIABLES

    assert ARTIFACT_QUOTA_ENV in names
    assert names.count(ARTIFACT_QUOTA_ENV) == 1


def test_public_application_manifest_contains_quota_contract() -> None:
    from weave_jacquard.mcp_build import (
        PUBLIC_APPLICATION_MANIFEST,
        PUBLIC_TOOL_MANIFEST,
    )

    assert ARTIFACT_QUOTA_ENV in PUBLIC_APPLICATION_MANIFEST["configuration_variables"]
    assert "artifact_storage_report" in PUBLIC_TOOL_MANIFEST["tool_names"]
