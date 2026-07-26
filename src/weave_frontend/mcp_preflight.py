"""Production MCP registration for one-call merge preflight."""

from __future__ import annotations

from functools import lru_cache

from .mcp_build import merge_impacts, merge_validation_sets
from .mcp_server import _result, mcp, workspace
from .merge_policy import MergePolicyRegistry
from .merge_preflight import MergePreflightService


@lru_cache(maxsize=1)
def merge_policies() -> MergePolicyRegistry:
    return MergePolicyRegistry(workspace())


@lru_cache(maxsize=1)
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
