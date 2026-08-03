"""Production MCP registration for artifact accounting and quota admission."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifact_quota import ArtifactQuotaService
from .artifact_storage import ArtifactStorageService
from .mcp_build import compiler_bridge
from .mcp_database_backup import database_backups
from .mcp_merge_candidate_test_runs import (
    merge_candidate_builds,
    merge_candidate_test_batches,
)
from .mcp_server import _result, mcp, workspace
from .mcp_test_batches import test_batches
from .mcp_test_runs import test_runs
from .mcp_tested_merge_attestations import tested_merge_attestations
from .quota_aware_compiler_bridge import install_quota_aware_compiler_bridge
from .runtime_container import runtime_config, runtime_service


def _artifact_roots() -> dict[str, Path]:
    """Resolve the complete live artifact-family root set."""

    return {
        "committed_builds": Path(compiler_bridge().build_root),
        "candidate_builds": Path(merge_candidate_builds().build_root),
        "test_runs": Path(test_runs().run_root),
        "test_batches": Path(test_batches().batch_root),
        "candidate_test_qualifications": Path(
            merge_candidate_test_batches().run_root
        ),
        "tested_merge_attestations": Path(
            tested_merge_attestations().attestation_root
        ),
        "database_backups": Path(database_backups().backup_root),
    }


@runtime_service(
    "artifact_storage",
    depends_on=(
        "compiler_bridge",
        "merge_candidate_builds",
        "test_runs",
        "test_batches",
        "merge_candidate_test_batches",
        "tested_merge_attestations",
        "database_backups",
    ),
)
def artifact_storage() -> ArtifactStorageService:
    """Return bounded accounting for all live retained-artifact roots."""

    return ArtifactStorageService(_artifact_roots())


@runtime_service(
    "artifact_quota",
    depends_on=(
        "workspace",
        "artifact_storage",
        "compiler_bridge",
        "merge_candidate_builds",
        "test_runs",
        "test_batches",
        "merge_candidate_test_batches",
        "tested_merge_attestations",
        "database_backups",
    ),
)
def artifact_quota() -> ArtifactQuotaService:
    """Return and attach the shared aggregate publication quota guard."""

    quota = ArtifactQuotaService(
        artifact_storage(),
        lock_path=workspace().db.path.parent / ".weave-artifact-quota.lock",
        max_bytes=runtime_config().artifact_max_bytes,
    )
    bridge = install_quota_aware_compiler_bridge(compiler_bridge())
    for service in (
        bridge,
        merge_candidate_builds(),
        test_runs(),
        test_batches(),
        merge_candidate_test_batches(),
        tested_merge_attestations(),
        database_backups(),
    ):
        service.artifact_quota = quota
    return quota


@mcp.tool()
def artifact_storage_report() -> dict[str, Any]:
    """Report bounded logical usage and aggregate publication quota state."""

    return _result(artifact_quota().report)
