"""Production MCP registration for immutable revert preview and publication."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from .mcp_build import merge_previews
from .mcp_server import _result, mcp, workspace
from .revert import RevertService


@lru_cache(maxsize=1)
def reverts() -> RevertService:
    """Return the shared stable-ID revert service."""

    return RevertService(workspace(), merge_previews())


def install_capability() -> None:
    """Discard stale revert composition when public capabilities are reinstalled."""

    reverts.cache_clear()


install_capability()


@mcp.tool()
def branch_revert_preview(
    project: str,
    branch: str,
    revision_id: str,
) -> dict[str, Any]:
    """Preview the inverse of one first-parent revision against the current branch."""

    return _result(lambda: reverts().preview(project, branch, revision_id))


@mcp.tool()
def branch_revert(
    project: str,
    branch: str,
    revision_id: str,
    preview_id: str,
    author: str = "revert-agent",
    message: str | None = None,
) -> dict[str, Any]:
    """Publish one exact reviewed inverse as a new immutable revision."""

    return _result(
        lambda: reverts().revert(
            project,
            branch,
            revision_id,
            preview_id=preview_id,
            author=author,
            message=message,
        )
    )
