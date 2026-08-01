"""Application-local installation of the canonical FastMCP tool registry."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .fastmcp_registry import FastMCPRegistryAdapter

if TYPE_CHECKING:
    from .mcp_capabilities import ApplicationContext


def install_registered_application_tools(
    context: ApplicationContext,
    registration_server: Any,
) -> tuple[str, ...]:
    """Install exact canonical tool objects onto one application server."""

    return FastMCPRegistryAdapter(context.server).replace_tools_from(
        registration_server
    )


__all__ = ["install_registered_application_tools"]
