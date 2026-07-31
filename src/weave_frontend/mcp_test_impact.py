"""Production MCP registration for exact-revision behavioral-test impact plans."""

from __future__ import annotations

from typing import Any

from .mcp_build import build_targets
from .mcp_server import _result, mcp, workspace
from .mcp_test_targets import test_targets
from .runtime_container import runtime_service
from .test_impact import (
    DEFAULT_TEST_IMPACT_EVIDENCE_LIMIT,
    DEFAULT_TEST_IMPACT_PAGE_SIZE,
    TestImpactPlanService,
)


@runtime_service(
    "test_impact_plans",
    depends_on=("workspace", "build_targets", "test_targets"),
)
def test_impact_plans() -> TestImpactPlanService:
    """Return the shared non-executing structural test-impact service."""

    return TestImpactPlanService(workspace(), build_targets(), test_targets())


@mcp.tool()
def test_impact_plan(
    project: str,
    base_revision_id: str,
    branch: str = "main",
    target_revision_id: str | None = None,
    start_after_name: str | None = None,
    limit: int = DEFAULT_TEST_IMPACT_PAGE_SIZE,
    evidence_limit: int = DEFAULT_TEST_IMPACT_EVIDENCE_LIMIT,
) -> dict[str, Any]:
    """Page structural test candidates between two exact immutable revisions."""

    return _result(
        lambda: test_impact_plans().page(
            project,
            base_revision_id,
            branch=branch,
            target_revision_id=target_revision_id,
            start_after_name=start_after_name,
            limit=limit,
            evidence_limit=evidence_limit,
        )
    )
