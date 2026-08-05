"""Production MCP registration for one-call merge preflight."""

from __future__ import annotations

from .mcp_build import merge_impacts, merge_validation_sets
from .mcp_server import _result, mcp, workspace
from .merge_policy import MergePolicyRegistry
from .merge_preflight import MergePreflightService
from .runtime import runtime_service


@runtime_service("merge_policies", depends_on=("workspace",))
def merge_policies() -> MergePolicyRegistry:
    return MergePolicyRegistry(workspace())


@runtime_service(
    "merge_preflights",
    depends_on=("merge_impacts", "merge_validation_sets", "merge_policies"),
)
def merge_preflights() -> MergePreflightService:
    return MergePreflightService(
        merge_impacts(),
        merge_validation_sets(),
        merge_policies(),
    )


@mcp.tool()
def branch_merge_preflight(
    project: str,
    target_branch: str,
    source_branch: str,
    preview_id: str | None = None,
    allow_uncovered_documents: bool = False,
) -> dict[str, object]:
    """Compose policy, impact, and all affected-target validation without mutation."""

    return _result(
        lambda: merge_preflights().run(
            project,
            target_branch,
            source_branch,
            preview_id=preview_id,
            allow_uncovered_documents=allow_uncovered_documents,
        )
    )
