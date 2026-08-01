"""Application-local installation of the canonical FastMCP tool registry."""

from __future__ import annotations

import asyncio
import inspect
from contextvars import ContextVar
from functools import wraps
from threading import Lock
from typing import TYPE_CHECKING, Any

from .application_runtime_binding import bind_application_runtime
from .fastmcp_registry import FastMCPRegistryAdapter, FastMCPRegistryError
from .runtime_container import RuntimeServices, runtime_services

if TYPE_CHECKING:
    from collections.abc import Callable

    from .mcp_capabilities import ApplicationContext

_active_runtime: ContextVar[
    tuple[RuntimeServices, asyncio.Task[Any] | None] | None
] = ContextVar(
    "weave_active_application_runtime",
    default=None,
)
_runtime_gate = Lock()


async def _acquire_runtime_gate() -> None:
    while not _runtime_gate.acquire(blocking=False):
        await asyncio.sleep(0)


async def _call_with_runtime(
    runtime: RuntimeServices,
    function: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> Any:
    active = _active_runtime.get()
    current_task = asyncio.current_task()
    if (
        active is not None
        and active[1] is current_task
        and runtime_services() is active[0]
    ):
        if active[0] is not runtime:
            raise RuntimeError(
                "nested tool invocation cannot switch application runtimes"
            )
        result = function(*args, **kwargs)
        return await result if inspect.isawaitable(result) else result

    await _acquire_runtime_gate()
    token = _active_runtime.set((runtime, current_task))
    try:
        with bind_application_runtime(runtime):
            result = function(*args, **kwargs)
            return await result if inspect.isawaitable(result) else result
    finally:
        _active_runtime.reset(token)
        _runtime_gate.release()


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

    @wraps(function)
    async def bound(*args: Any, **kwargs: Any) -> Any:
        return await _call_with_runtime(runtime, function, args, kwargs)

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
    "install_registered_application_tools",
]
