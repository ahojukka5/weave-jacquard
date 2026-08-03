"""Production MCP registration for artifact accounting and quota admission."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .artifact_quota import ArtifactQuotaService
from .artifact_reachability import ArtifactReconciliationService
from .artifact_reconciliation import (
    RetainedArtifactFamily,
    RetainedArtifactInventoryService,
)
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

_ARTIFACT_ID_32 = re.compile(r"^[0-9a-f]{32}$")
_ARTIFACT_ID_64 = re.compile(r"^[0-9a-f]{64}$")


def _artifact_services() -> dict[str, tuple[Any, str, re.Pattern[str]]]:
    """Resolve every retained family to its verifier and root attribute."""

    return {
        "committed_builds": (
            compiler_bridge(),
            "build_root",
            _ARTIFACT_ID_32,
        ),
        "candidate_builds": (
            merge_candidate_builds(),
            "build_root",
            _ARTIFACT_ID_32,
        ),
        "test_runs": (
            test_runs(),
            "run_root",
            _ARTIFACT_ID_32,
        ),
        "test_batches": (
            test_batches(),
            "batch_root",
            _ARTIFACT_ID_32,
        ),
        "candidate_test_qualifications": (
            merge_candidate_test_batches(),
            "run_root",
            _ARTIFACT_ID_32,
        ),
        "tested_merge_attestations": (
            tested_merge_attestations(),
            "attestation_root",
            _ARTIFACT_ID_32,
        ),
        "database_backups": (
            database_backups(),
            "backup_root",
            _ARTIFACT_ID_64,
        ),
    }


def _artifact_roots() -> dict[str, Path]:
    """Resolve the complete live artifact-family root set."""

    return {
        name: Path(getattr(service, root_attribute))
        for name, (service, root_attribute, _pattern) in _artifact_services().items()
    }


def _artifact_families() -> tuple[RetainedArtifactFamily, ...]:
    """Bind every live family root to its normal production verifier."""

    return tuple(
        RetainedArtifactFamily(
            name,
            Path(getattr(service, root_attribute)),
            pattern,
            service.get,
        )
        for name, (service, root_attribute, pattern) in _artifact_services().items()
    )


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
    "artifact_inventory",
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
def artifact_inventory() -> RetainedArtifactInventoryService:
    """Return bounded verified membership for all retained-artifact families."""

    return RetainedArtifactInventoryService(_artifact_families())


@runtime_service(
    "artifact_reconciliation",
    depends_on=("workspace", "artifact_inventory"),
)
def artifact_reconciliation() -> ArtifactReconciliationService:
    """Return immutable database-to-artifact reachability reconciliation."""

    return ArtifactReconciliationService(workspace().db, artifact_inventory())


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


@mcp.tool()
def artifact_reconciliation_report() -> dict[str, Any]:
    """Report deterministic database-to-artifact reachability evidence."""

    return _result(artifact_reconciliation().report)
