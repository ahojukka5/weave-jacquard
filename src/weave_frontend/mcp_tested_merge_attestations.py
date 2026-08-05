"""Production MCP registration for tested-merge state-identity attestations."""

from __future__ import annotations

from typing import Any

from .mcp_merge_candidate_test_runs import merge_candidate_test_batches
from .mcp_server import _result, mcp, workspace
from .runtime import TestedMergeAttestationService, runtime_config, runtime_service


@runtime_service(
    "tested_merge_attestations",
    depends_on=("workspace", "merge_candidate_test_batches"),
)
def tested_merge_attestations() -> TestedMergeAttestationService:
    """Return the shared immutable tested-merge attestation service."""

    return TestedMergeAttestationService(
        workspace(),
        merge_candidate_test_batches(),
        attestation_root=runtime_config().merge_attestation_root,
    )


@mcp.tool()
def tested_merge_attest(
    qualification_id: str,
    merged_revision_id: str,
) -> dict[str, Any]:
    """Attest that one committed merge exactly equals a tested virtual candidate."""

    return _result(
        lambda: tested_merge_attestations().attest(
            qualification_id,
            merged_revision_id,
        )
    )


@mcp.tool()
def tested_merge_attestation_get(attestation_id: str) -> dict[str, Any]:
    """Read and reverify one immutable tested-merge attestation."""

    return _result(lambda: tested_merge_attestations().get(attestation_id))
