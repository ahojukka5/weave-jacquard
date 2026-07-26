"""Production MCP registration for atomic context and policy publication."""

from __future__ import annotations

from typing import Any

from . import mcp_policy as _policy
from . import mcp_preflight as _preflight
from .concurrent_merge_policy import MergePolicyRegistry
from .mcp_server import _result, mcp, workspace

# Policy and preflight caches are lightweight service compositions. Replace the
# registry implementation and clear any test-populated instances before calls.
_preflight.MergePolicyRegistry = MergePolicyRegistry
_preflight.merge_preflights.cache_clear()
_preflight.merge_policies.cache_clear()

for _tool_name in ("context_add", "merge_policy_set"):
    mcp.remove_tool(_tool_name)


@mcp.tool()
def context_add(
    project: str,
    branch: str,
    scope_kind: str,
    scope_name: str,
    title: str,
    body: str,
    expected_revision_id: str | None = None,
    author: str = "agent",
) -> dict[str, Any]:
    """Publish context and its revision atomically with optional concurrency."""

    return _result(
        lambda: workspace().add_context(
            project,
            branch,
            scope_kind=scope_kind,
            scope_name=scope_name,
            title=title,
            body=body,
            expected_revision_id=expected_revision_id,
            author=author,
        )
    )


@mcp.tool()
def merge_policy_set(
    project: str,
    branch: str = "main",
    require_preflight: bool = True,
    require_affected_validation: bool = True,
    allow_uncovered_documents: bool = False,
    max_affected_targets: int = 64,
    expected_revision_id: str | None = None,
    author: str = "policy-agent",
) -> dict[str, Any]:
    """Publish one policy document and revision atomically."""

    return _result(
        lambda: _preflight.merge_policies().set(
            project,
            branch,
            require_preflight=require_preflight,
            require_affected_validation=require_affected_validation,
            allow_uncovered_documents=allow_uncovered_documents,
            max_affected_targets=max_affected_targets,
            expected_revision_id=expected_revision_id,
            author=author,
        )
    )


# Keep the module reference alive for explicit final registration ordering.
_ = _policy
