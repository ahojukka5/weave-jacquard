"""MCP tools for unpublished working edit candidates."""

from __future__ import annotations

from typing import Any

from .edit_candidates import EditCandidateService
from .mcp_server import _result, mcp, workspace
from .runtime import runtime_service


@runtime_service("edit_candidates", depends_on=("workspace",))
def edit_candidates() -> EditCandidateService:
    return EditCandidateService(workspace())


@mcp.tool()
def candidate_open(
    project: str,
    name: str,
    branch: str = "main",
    base_revision_id: str | None = None,
) -> dict[str, Any]:
    """Open an unpublished candidate from a branch head or exact revision."""

    return _result(
        lambda: edit_candidates().open(
            project,
            name,
            branch=branch,
            base_revision_id=base_revision_id,
        )
    )


@mcp.tool()
def candidate_inspect(project: str, candidate_id: str) -> dict[str, Any]:
    """Inspect candidate identity, edits, qualification, and publication."""

    return _result(lambda: edit_candidates().inspect(project, candidate_id))


@mcp.tool()
def candidate_apply_batch(
    project: str,
    candidate_id: str,
    document: str,
    operations: list[dict[str, Any]],
    expected_revision_id: str | None = None,
    message: str | None = None,
    author: str = "agent",
    include_operation_results: bool = False,
) -> dict[str, Any]:
    """Apply structural edits to a candidate without advancing a branch."""

    return _result(
        lambda: edit_candidates().apply_batch(
            project,
            candidate_id,
            document,
            operations,
            expected_revision_id=expected_revision_id,
            message=message,
            author=author,
            include_operation_results=include_operation_results,
        )
    )


@mcp.tool()
def candidate_qualify(
    project: str,
    candidate_id: str,
    level: str = "syntactic",
    expected_revision_id: str | None = None,
) -> dict[str, Any]:
    """Qualify the exact candidate head at a named evidence level."""

    return _result(
        lambda: edit_candidates().qualify(
            project,
            candidate_id,
            level=level,
            expected_revision_id=expected_revision_id,
        )
    )


@mcp.tool()
def candidate_publish(
    project: str,
    candidate_id: str,
    branch: str,
    require_level: str | None = None,
    expected_base_revision_id: str | None = None,
    expected_revision_id: str | None = None,
) -> dict[str, Any]:
    """Publish a candidate head onto a branch when qualification still matches."""

    return _result(
        lambda: edit_candidates().publish(
            project,
            candidate_id,
            branch,
            require_level=require_level,
            expected_base_revision_id=expected_base_revision_id,
            expected_revision_id=expected_revision_id,
        )
    )


@mcp.tool()
def candidate_abandon(project: str, candidate_id: str) -> dict[str, Any]:
    """Abandon an open candidate without moving any branch."""

    return _result(lambda: edit_candidates().abandon(project, candidate_id))


@mcp.tool()
def candidate_revert_last(project: str, candidate_id: str) -> dict[str, Any]:
    """Restore a candidate to the previous revision in its edit chain."""

    return _result(lambda: edit_candidates().revert_last(project, candidate_id))


@mcp.tool()
def candidate_replay(
    project: str,
    name: str,
    document: str,
    operations: list[dict[str, Any]],
    branch: str = "main",
    base_revision_id: str | None = None,
) -> dict[str, Any]:
    """Replay a recorded structural operation list onto a new candidate."""

    return _result(
        lambda: edit_candidates().replay(
            project,
            name,
            operations,
            branch=branch,
            base_revision_id=base_revision_id,
            document=document,
        )
    )
