"""Application-local installation of capability-owned MCP tool models."""

from __future__ import annotations

from types import ModuleType
from typing import TYPE_CHECKING, Any

from .fastmcp_registry import FastMCPRegistryAdapter, FastMCPRegistryError

if TYPE_CHECKING:
    from .mcp_capabilities import ApplicationContext

_CANONICAL_FUNCTION_ATTRIBUTE = (
    "__weave_jacquard_canonical_tool_function__"
)


def _canonical_function(name: str, tool: Any) -> Any:
    function = getattr(tool, "fn", None)
    canonical = getattr(function, _CANONICAL_FUNCTION_ATTRIBUTE, function)
    if not callable(canonical):
        raise FastMCPRegistryError(
            f"registered capability tool {name!r} has no canonical callable"
        )
    return canonical


def capability_tool_names(
    registration_server: Any,
    module: ModuleType,
) -> tuple[str, ...]:
    """Return tools whose canonical callable is defined by one capability module."""

    if not isinstance(module, ModuleType):
        raise TypeError("capability tool ownership requires a module")

    tools = FastMCPRegistryAdapter(registration_server).tool_objects()
    return tuple(
        sorted(
            name
            for name, tool in tools.items()
            if getattr(_canonical_function(name, tool), "__module__", None)
            == module.__name__
        )
    )


def _clone_tool_model(name: str, tool: Any) -> Any:
    model_copy = getattr(tool, "model_copy", None)
    if not callable(model_copy):
        raise FastMCPRegistryError(
            f"capability MCP tool {name!r} cannot be cloned locally"
        )
    try:
        clone = model_copy(update={})
    except Exception as exc:
        raise FastMCPRegistryError(
            f"capability MCP tool {name!r} could not be cloned locally"
        ) from exc
    if clone is tool:
        raise FastMCPRegistryError(
            f"capability MCP tool {name!r} reused its shared object"
        )
    if getattr(clone, "fn", None) is not getattr(tool, "fn", None):
        raise FastMCPRegistryError(
            f"capability MCP tool {name!r} changed its canonical callable"
        )
    return clone


def install_context_capability_tools(
    context: ApplicationContext,
    registration_server: Any,
    module: ModuleType,
) -> tuple[str, ...]:
    """Install one capability module's tools as application-local models."""

    selected = capability_tool_names(registration_server, module)
    if not selected:
        return ()

    source = FastMCPRegistryAdapter(registration_server)
    source_objects = source.tool_objects()
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
                f"capability MCP tool {name!r} was not made application-local"
            )
        if getattr(installed_objects[name], "fn", None) is not getattr(
            source_objects[name],
            "fn",
            None,
        ):
            raise FastMCPRegistryError(
                f"capability MCP tool {name!r} lost its canonical callable"
            )
    return installed


__all__ = [
    "capability_tool_names",
    "install_context_capability_tools",
]
