"""Production MCP registration for bounded artifact-storage accounting."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from .artifact_storage import ArtifactStorageService
from .mcp_build import compiler_bridge
from .mcp_merge_candidate_test_runs import (
    merge_candidate_builds,
    merge_candidate_test_batches,
)
from .mcp_server import _result, mcp
from .mcp_test_batches import test_batches
from .mcp_test_runs import test_runs
from .mcp_tested_merge_attestations import tested_merge_attestations


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
    }


@lru_cache(maxsize=1)
def artifact_storage() -> ArtifactStorageService:
    """Return bounded accounting for all live retained-artifact roots."""

    return ArtifactStorageService(_artifact_roots())


def install_capability() -> None:
    """Discard stale root composition when capabilities are reinstalled."""

    artifact_storage.cache_clear()


@mcp.tool()
def artifact_storage_report() -> dict[str, Any]:
    """Report bounded path-redacted logical usage for all artifact stores."""

    return _result(artifact_storage().report)
