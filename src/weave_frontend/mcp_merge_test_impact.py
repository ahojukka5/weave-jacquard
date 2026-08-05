"""Production MCP registration for virtual merge-candidate test impact plans."""

from __future__ import annotations

from typing import Any

from .mcp_build import build_targets, merge_previews
from .mcp_server import _result, mcp
from .mcp_test_targets import test_targets
from .merge_test_impact import MergeCandidateTestImpactService
from .runtime import runtime_service
from .test_impact import (
    DEFAULT_TEST_IMPACT_EVIDENCE_LIMIT,
    DEFAULT_TEST_IMPACT_PAGE_SIZE,
)


@runtime_service(
    "merge_test_impact_plans",
    depends_on=("merge_previews", "build_targets", "test_targets"),
)
def merge_test_impact_plans() -> MergeCandidateTestImpactService:
    """Return the shared virtual merge-candidate impact service."""

    return MergeCandidateTestImpactService(
        merge_previews(),
        build_targets(),
        test_targets(),
    )


@mcp.tool()
def branch_merge_test_impact(
    project: str,
    target_branch: str,
    source_branch: str,
    preview_id: str | None = None,
    start_after_name: str | None = None,
    limit: int = DEFAULT_TEST_IMPACT_PAGE_SIZE,
    evidence_limit: int = DEFAULT_TEST_IMPACT_EVIDENCE_LIMIT,
) -> dict[str, Any]:
    """Page structural test candidates for one exact clean merge preview."""

    return _result(
        lambda: merge_test_impact_plans().page(
            project,
            target_branch,
            source_branch,
            preview_id=preview_id,
            start_after_name=start_after_name,
            limit=limit,
            evidence_limit=evidence_limit,
        )
    )
