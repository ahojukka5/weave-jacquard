"""Application-local installation of the canonical FastMCP tool registry."""

from __future__ import annotations

import inspect
from functools import wraps
from typing import TYPE_CHECKING, Any

from .application_runtime_binding import bind_application_runtime
from .fastmcp_registry import FastMCPRegistryAdapter, FastMCPRegistryError
from .runtime_container import RuntimeServices

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from .mcp_capabilities import ApplicationContext

_CANONICAL_FUNCTION_ATTRIBUTE = (
    "__weave_jacquard_canonical_tool_function__"
)


async def _call_with_runtime(
    runtime: RuntimeServices,
    function: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> Any:
    with bind_application_runtime(runtime):
        result = function(*args, **kwargs)
        return await result if inspect.isawaitable(result) else result


def _canonical_function(name: str, function: Any) -> Callable[..., Any]:
    canonical = getattr(function, _CANONICAL_FUNCTION_ATTRIBUTE, function)
    if not callable(canonical):
        raise FastMCPRegistryError(
            f"registered tool {name!r} retained an invalid canonical callable"
        )
    return canonical


def _bind_tool_to_runtime(
    name: str,
    tool: Any,
    runtime: RuntimeServices,
) -> Any:
    function = getattr(tool, "fn", None)
    model_copy = getattr(tool, "model_copy", None)
    if not callable(function) or not callable(model_copy):
        raise FastMCPRegistryError(
            f"registered tool {name!r} cannot be cloned for runtime binding"
        )
    canonical = _canonical_function(name, function)

    @wraps(canonical)
    async def bound(*args: Any, **kwargs: Any) -> Any:
        return await _call_with_runtime(runtime, canonical, args, kwargs)

    setattr(bound, _CANONICAL_FUNCTION_ATTRIBUTE, canonical)
    try:
        clone = model_copy(update={"fn": bound, "is_async": True})
    except Exception as exc:
        raise FastMCPRegistryError(
            f"registered tool {name!r} could not be cloned for runtime binding"
        ) from exc
    if clone is tool:
        raise FastMCPRegistryError(
            f"registered tool {name!r} runtime clone reused the source object"
        )
    if getattr(clone, "fn", None) is not bound:
        raise FastMCPRegistryError(
            f"registered tool {name!r} runtime clone did not retain its wrapper"
        )
    if getattr(clone, "is_async", None) is not True:
        raise FastMCPRegistryError(
            f"registered tool {name!r} runtime clone is not asynchronous"
        )
    return clone


def install_registered_application_tools(
    context: ApplicationContext,
    registration_server: Any,
) -> tuple[str, ...]:
    """Install exact canonical tool objects onto one application server."""

    return FastMCPRegistryAdapter(context.server).replace_tools_from(
        registration_server
    )


def finalize_registered_application_tools(
    context: ApplicationContext,
    registration_server: Any,
    *,
    local_contract_names: Iterable[str] = (),
) -> tuple[str, ...]:
    """Retain canonical names and verify one explicitly assembled registry."""

    source = FastMCPRegistryAdapter(registration_server)
    target = FastMCPRegistryAdapter(context.server)
    source_names = source.tool_names()
    expected_names = set(source_names)
    local_names = set(local_contract_names)
    if any(not isinstance(name, str) or not name for name in local_names):
        raise FastMCPRegistryError(
            "application-local contract names must be non-empty strings"
        )
    unknown_local = tuple(sorted(local_names - expected_names))
    if unknown_local:
        raise FastMCPRegistryError(
            f"application-local contracts are not canonical tools {unknown_local!r}"
        )

    target_names = set(target.tool_names(allow_empty=True))
    missing = tuple(sorted(expected_names - target_names))
    if missing:
        extra = tuple(sorted(target_names - expected_names))
        raise FastMCPRegistryError(
            "explicit application tool assembly is incomplete: "
            f"missing={missing!r}, extra={extra!r}"
        )
    installed_names = target.retain_tools(source_names)

    source_contracts = {
        contract["name"]: contract for contract in source.tool_contracts()
    }
    target_contracts = {
        contract["name"]: contract for contract in target.tool_contracts()
    }
    mismatched = tuple(
        name
        for name in source_names
        if name not in local_names
        and target_contracts[name] != source_contracts[name]
    )
    if mismatched:
        raise FastMCPRegistryError(
            "explicit application tool assembly changed canonical contracts "
            f"{mismatched!r}"
        )
    return installed_names


def bind_registered_application_tools(
    context: ApplicationContext,
) -> tuple[str, ...]:
    """Clone every application tool with request-time runtime binding."""

    return FastMCPRegistryAdapter(context.server).replace_tools_from(
        context.server,
        transform=lambda name, tool: _bind_tool_to_runtime(
            name,
            tool,
            context.runtime,
        ),
    )


__all__ = [
    "bind_registered_application_tools",
    "finalize_registered_application_tools",
    "install_registered_application_tools",
]
