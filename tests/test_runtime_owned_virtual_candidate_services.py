from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import weave_frontend.mcp_build as build_module
import weave_frontend.mcp_merge_candidate_test_runs as candidate_module
import weave_frontend.mcp_merge_test_impact as impact_module
import weave_frontend.mcp_test_targets as target_module
import weave_frontend.mcp_tested_merge_attestations as attestation_module
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
            "WEAVE_MERGE_BUILD_ROOT": str(tmp_path / "candidate-builds"),
            "WEAVE_MERGE_TEST_RUN_ROOT": str(tmp_path / "candidate-tests"),
            "WEAVE_MERGE_ATTESTATION_ROOT": str(tmp_path / "attestations"),
        }
    )


def test_virtual_candidate_services_are_runtime_owned(tmp_path: Path) -> None:
    workspace = SimpleNamespace(db=SimpleNamespace(path=tmp_path / "runtime.db"))
    compiler = SimpleNamespace(build_root=tmp_path / "committed-builds")
    services = RuntimeServices(
        _config(tmp_path),
        workspace_factory=lambda _config: workspace,
        compiler_bridge_factory=lambda _workspace, _config: compiler,
    )

    with _isolated_process_runtime():
        install_runtime_services(services)

        previews = build_module.merge_previews()
        targets = build_module.build_targets()
        tests = target_module.test_targets()
        builds = candidate_module.merge_candidate_builds()
        inspection = candidate_module.merge_candidate_build_inspection()
        batches = candidate_module.merge_candidate_test_batches()
        impacts = impact_module.merge_test_impact_plans()
        attestations = attestation_module.tested_merge_attestations()

        assert builds.previews is previews
        assert builds.build_targets is targets
        assert builds.compiler is compiler
        assert inspection.bridge is builds
        assert batches.previews is previews
        assert batches.tests is tests
        assert batches.builds is builds
        assert impacts.previews is previews
        assert impacts.build_targets is targets
        assert impacts.tests is tests
        assert attestations.workspace is workspace
        assert attestations.qualifications is batches

        entries = {item["name"]: item for item in services.service_manifest()["services"]}
        assert entries["merge_candidate_builds"]["depends_on"] == [
            "build_targets",
            "compiler_bridge",
            "merge_previews",
        ]
        assert entries["merge_candidate_build_inspection"]["depends_on"] == [
            "merge_candidate_builds"
        ]
        assert entries["merge_candidate_test_batches"]["depends_on"] == [
            "merge_candidate_builds",
            "merge_previews",
            "test_targets",
        ]
        assert entries["merge_test_impact_plans"]["depends_on"] == [
            "build_targets",
            "merge_previews",
            "test_targets",
        ]
        assert entries["tested_merge_attestations"]["depends_on"] == [
            "merge_candidate_test_batches",
            "workspace",
        ]

        services.clear_service("workspace")

        for factory in (
            candidate_module.merge_candidate_builds,
            candidate_module.merge_candidate_build_inspection,
            candidate_module.merge_candidate_test_batches,
            impact_module.merge_test_impact_plans,
            attestation_module.tested_merge_attestations,
        ):
            assert factory.cache_info().currsize == 0
