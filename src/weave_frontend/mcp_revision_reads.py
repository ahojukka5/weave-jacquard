"""Production MCP registration for revision-pinned render and search reads."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from .mcp_server import _result, mcp, workspace
from .revision_reads import RevisionReadService

mcp.remove_tool("node_find")
mcp.remove_tool("program_render")


@lru_cache(maxsize=1)
def revision_reads() -> RevisionReadService:
    return RevisionReadService(workspace())


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
