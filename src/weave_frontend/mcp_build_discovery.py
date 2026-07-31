"""Production MCP registration for bounded verified build discovery."""

from __future__ import annotations

from .mcp_build import compiler_bridge
from .mcp_server import _result, mcp
from .runtime_container import runtime_service
from .verified_build_discovery import BuildDiscoveryService


@runtime_service("build_discovery", depends_on=("compiler_bridge",))
def build_discovery() -> BuildDiscoveryService:
    return BuildDiscoveryService(compiler_bridge())


@mcp.tool()
def build_list_page(
    project: str,
    branch: str | None = None,
    revision_id: str | None = None,
    status: str | None = None,
    document: str | None = None,
    target: str | None = None,
    start_after_build_id: str | None = None,
    catalog_id: str | None = None,
    limit: int = 50,
) -> dict[str, object]:
    """Discover one bounded page of verified immutable stored builds."""

    return _result(
        lambda: build_discovery().page(
            project,
            branch=branch,
            revision_id=revision_id,
            status=status,
            document=document,
            target=target,
            start_after_build_id=start_after_build_id,
            catalog_id=catalog_id,
            limit=limit,
        )
    )
