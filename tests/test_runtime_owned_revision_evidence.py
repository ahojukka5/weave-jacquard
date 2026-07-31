from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

import weave_frontend.mcp_revision_evidence as evidence_module
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


def _publisher(root_name: str, root: Path, attribute: str) -> SimpleNamespace:
    return SimpleNamespace(
        **{
            attribute: root,
            "get": lambda artifact_id: {
                "root": root_name,
                "artifact_id": artifact_id,
            },
        }
    )


def test_revision_evidence_is_runtime_owned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = SimpleNamespace()
    builds = _publisher("build", tmp_path / "builds", "build_root")
    runs = _publisher("run", tmp_path / "runs", "run_root")
    batches = _publisher("batch", tmp_path / "batches", "batch_root")
    qualifications = SimpleNamespace(run_root=tmp_path / "qualifications")
    attestations = _publisher(
        "attestation",
        tmp_path / "attestations",
        "attestation_root",
    )

    monkeypatch.setattr(evidence_module, "workspace", lambda: workspace)
    monkeypatch.setattr(evidence_module, "compiler_bridge", lambda: builds)
    monkeypatch.setattr(evidence_module, "test_runs", lambda: runs)
    monkeypatch.setattr(evidence_module, "test_batches", lambda: batches)
    monkeypatch.setattr(
        evidence_module,
        "merge_candidate_test_batches",
        lambda: qualifications,
    )
    monkeypatch.setattr(
        evidence_module,
        "tested_merge_attestations",
        lambda: attestations,
    )

    runtime = RuntimeServices(
        _config(tmp_path),
        workspace_factory=lambda _config: workspace,
        compiler_bridge_factory=lambda _workspace, _config: builds,
    )

    with _isolated_process_runtime():
        install_runtime_services(runtime)

        evidence = evidence_module.revision_evidence()

        assert evidence.workspace is workspace
        assert evidence.qualifications is qualifications
        assert evidence._stores["build"].root == builds.build_root.resolve()
        assert evidence._stores["build"].getter is builds.get
        assert evidence._stores["test_run"].root == runs.run_root.resolve()
        assert evidence._stores["test_run"].getter is runs.get
        assert evidence._stores["test_batch"].root == batches.batch_root.resolve()
        assert evidence._stores["test_batch"].getter is batches.get
        attestation_store = evidence._stores["tested_merge_attestation"]
        assert attestation_store.root == attestations.attestation_root.resolve()
        assert attestation_store.getter is attestations.get

        entries = {
            item["name"]: item
            for item in runtime.service_manifest()["services"]
        }
        assert entries["revision_evidence"]["depends_on"] == [
            "compiler_bridge",
            "merge_candidate_test_batches",
            "test_batches",
            "test_runs",
            "tested_merge_attestations",
            "workspace",
        ]

        runtime.clear_service("test_runs")

        assert evidence_module.revision_evidence.cache_info().currsize == 0
