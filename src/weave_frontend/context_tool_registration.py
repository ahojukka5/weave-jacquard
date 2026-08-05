"""Application-local cloning for foundational MCP tool models."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .fastmcp_registry import FastMCPRegistryAdapter, FastMCPRegistryError

if TYPE_CHECKING:
    from .mcp_capabilities import ApplicationContext


CORE_TOOL_NAMES: tuple[str, ...] = (
    "weave_help",
    "grammar_help",
    "project_initialize",
    "branch_create",
    "branch_list",
    "branch_history",
    "branch_merge",
    "program_create",
    "program_import",
    "program_list",
    "node_create_form",
    "node_add_atom",
    "node_set_atom",
    "node_delete",
    "node_move",
    "node_wrap",
    "node_inspect",
    "node_find",
    "program_render",
    "program_validate",
    "context_add",
    "context_get",
)


def _clone_tool_model(name: str, tool: Any) -> Any:
    model_copy = getattr(tool, "model_copy", None)
    if not callable(model_copy):
        raise FastMCPRegistryError(f"foundational MCP tool {name!r} cannot be cloned locally")
    try:
        clone = model_copy(update={})
    except Exception as exc:
        raise FastMCPRegistryError(
            f"foundational MCP tool {name!r} could not be cloned locally"
        ) from exc
    if clone is tool:
        raise FastMCPRegistryError(f"foundational MCP tool {name!r} reused its shared object")
    if getattr(clone, "fn", None) is not getattr(tool, "fn", None):
        raise FastMCPRegistryError(f"foundational MCP tool {name!r} changed its canonical callable")
    return clone


def install_context_core_tools(
    context: ApplicationContext,
    registration_server: Any,
) -> tuple[str, ...]:
    """Install foundational tools as application-local models."""

    source = FastMCPRegistryAdapter(registration_server)
    source_objects = source.tool_objects()
    selected = tuple(name for name in CORE_TOOL_NAMES if name in source_objects)
    if not selected:
        raise FastMCPRegistryError(
            "canonical application registry contains no foundational MCP tools"
        )

    target = FastMCPRegistryAdapter(context.server)
    installed = target.install_tools_from(
        registration_server,
        selected,
        transform=_clone_tool_model,
    )
    installed_objects = target.tool_objects()

    for name in installed:
        if installed_objects[name] is source_objects[name]:
            raise FastMCPRegistryError(
                f"foundational MCP tool {name!r} was not made application-local"
            )
        if getattr(installed_objects[name], "fn", None) is not getattr(
            source_objects[name],
            "fn",
            None,
        ):
            raise FastMCPRegistryError(
                f"foundational MCP tool {name!r} lost its canonical callable"
            )
    return installed


__all__ = [
    "CORE_TOOL_NAMES",
    "install_context_core_tools",
]
