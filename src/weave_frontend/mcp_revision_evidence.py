"""Production MCP registration for bounded verified revision evidence graphs."""

from __future__ import annotations

from typing import Any

from .mcp_build import compiler_bridge
from .mcp_merge_candidate_test_runs import merge_candidate_test_batches
from .mcp_server import _result, mcp, workspace
from .mcp_test_batches import test_batches
from .mcp_test_runs import test_runs
from .mcp_tested_merge_attestations import tested_merge_attestations
from .revision_evidence import RevisionEvidenceService
from .runtime_container import runtime_service


@runtime_service(
    "revision_evidence",
    depends_on=(
        "workspace",
        "compiler_bridge",
        "test_runs",
        "test_batches",
        "merge_candidate_test_batches",
        "tested_merge_attestations",
    ),
)
def revision_evidence() -> RevisionEvidenceService:
    """Return the shared retained-evidence discovery service."""

    return RevisionEvidenceService(
        workspace(),
        compiler_bridge(),
        test_runs(),
        test_batches(),
        merge_candidate_test_batches(),
        tested_merge_attestations(),
    )


@mcp.tool()
def revision_evidence_page(
    project: str,
    revision_id: str,
    kind: str,
    start_after_id: str | None = None,
    catalog_id: str | None = None,
    limit: int = 25,
    scan_limit: int = 100,
) -> dict[str, Any]:
    """Discover one bounded verified graph page for an exact retained-evidence kind."""

    return _result(
        lambda: revision_evidence().page(
            project,
            revision_id,
            kind,
            start_after_id=start_after_id,
            catalog_id=catalog_id,
            limit=limit,
            scan_limit=scan_limit,
        )
    )
