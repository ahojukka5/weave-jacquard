"""Production MCP registration for reproducible branch creation."""

from __future__ import annotations

from typing import Any

from .mcp_server import _result, mcp, workspace

mcp.remove_tool("branch_create")


@mcp.tool()
def branch_create(
    project: str,
    branch: str,
    from_branch: str = "main",
    expected_revision_id: str | None = None,
) -> dict[str, Any]:
    """Fork a current branch head with optional optimistic concurrency."""

    return _result(
        lambda: workspace().create_branch(
            project,
            branch,
            from_branch=from_branch,
            expected_revision_id=expected_revision_id,
        )
    )


@mcp.tool()
def branch_create_at_revision(
    project: str,
    branch: str,
    revision_id: str,
) -> dict[str, Any]:
    """Fork one exact immutable project revision without moving another branch."""

    return _result(
        lambda: workspace().create_branch_at_revision(
            project,
            branch,
            revision_id,
        )
    )
