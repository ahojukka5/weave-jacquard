"""Production MCP registration for revision-pinned render and search reads."""

from __future__ import annotations

from typing import Any

from .mcp_server import _result, mcp, workspace
from .revision_reads import RevisionReadService
from .runtime import runtime_service

for _tool_name in ("branch_history", "node_find", "program_render"):
    mcp.remove_tool(_tool_name)


@runtime_service("revision_reads", depends_on=("workspace",))
def revision_reads() -> RevisionReadService:
    return RevisionReadService(workspace())


@mcp.tool()
def branch_history(
    project: str,
    branch: str = "main",
    limit: int = 50,
) -> dict[str, Any]:
    """Read a validated bounded first-parent prefix with truncation evidence."""

    return _result(lambda: workspace().history_page(project, branch, limit=limit))


@mcp.tool()
def node_find(
    project: str,
    branch: str,
    document: str,
    head: str | None = None,
    kind: str | None = None,
    value: Any | None = None,
    limit: int = 50,
    revision_id: str | None = None,
) -> dict[str, Any]:
    """Find stable nodes at a branch head or exact immutable revision."""

    response = _result(
        lambda: revision_reads().find(
            project,
            branch,
            document,
            head=head,
            kind=kind,
            value=value,
            limit=limit,
            revision_id=revision_id,
        )
    )
    if response.get("ok") is True:
        read = dict(response["result"])
        response["result"] = read.pop("matches")
        response.update(read)
    return response


@mcp.tool()
def program_render(
    project: str,
    branch: str,
    document: str,
    annotated: bool = True,
    annotate_atoms: bool = False,
    revision_id: str | None = None,
) -> dict[str, Any]:
    """Render a branch-head or exact-revision canonical or annotated source view."""

    return _result(
        lambda: revision_reads().render(
            project,
            branch,
            document,
            annotated=annotated,
            annotate_atoms=annotate_atoms,
            revision_id=revision_id,
        )
    )
