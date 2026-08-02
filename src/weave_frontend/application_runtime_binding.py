"""Scoped application-runtime binding for capability composition and calls."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from . import runtime_container as _runtime
from .runtime_container import RuntimeServices


@contextmanager
def bind_application_runtime(
    services: RuntimeServices,
) -> Iterator[RuntimeServices]:
    """Select one runtime within the current context and inherited child tasks."""

    token = _runtime._bind_runtime_services(services)
    try:
        yield services
    finally:
        _runtime._reset_bound_runtime_services(token)


__all__ = ["bind_application_runtime"]
