"""Application-local installation of final MCP guidance."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .fastmcp_registry import FastMCPRegistryAdapter, FastMCPRegistryError

if TYPE_CHECKING:
    from .mcp_capabilities import ApplicationContext

_HELP_DESCRIPTION = (
    "Explain structural, revision, checkpoint, project supervision, "
    "merge queues, merge trains, test definitions, strict test runs, "
    "explicit test batches, test impact plans, virtual candidate "
    "qualification, tested-merge attestations, revision evidence graphs, "
    "revisioned task contracts, scoped edits, immutable reverts, selected "
    "preflight, resume, validation, build, verified database backup, "
    "artifact storage, and runtime identity workflows."
)


def install_context_guidance(
    context: ApplicationContext,
    guidance_module: Any,
) -> str:
    """Install the final instructions and help tool on one application server."""

    instructions = getattr(guidance_module, "INSTRUCTIONS", None)
    help_function = getattr(guidance_module, "weave_help", None)
    if not isinstance(instructions, str) or not instructions:
        raise TypeError("application guidance requires non-empty INSTRUCTIONS")
    if not callable(help_function):
        raise TypeError("application guidance requires a callable weave_help")

    server = context.server
    adapter = FastMCPRegistryAdapter(server)
    if "weave_help" in adapter.tool_names(allow_empty=True):
        server.remove_tool("weave_help")
    server._mcp_server.instructions = instructions
    server.add_tool(
        help_function,
        name="weave_help",
        description=_HELP_DESCRIPTION,
    )

    if "weave_help" not in adapter.tool_names(allow_empty=True):
        raise FastMCPRegistryError("application guidance did not register weave_help")
    return "weave_help"


__all__ = ["install_context_guidance"]
