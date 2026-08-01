"""Scoped application-runtime binding for capability composition."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from . import runtime_container as _runtime
from .runtime_container import RuntimeClosedError, RuntimeServices


@contextmanager
def bind_application_runtime(
    services: RuntimeServices,
) -> Iterator[RuntimeServices]:
    """Temporarily select one runtime while capability modules are composed."""

    if not isinstance(services, RuntimeServices):
        raise TypeError("services must be a RuntimeServices instance")
    if services.closed:
        raise RuntimeClosedError("cannot bind a closed runtime container")

    with _runtime._runtime_lock:
        previous_config = _runtime._runtime_config
        previous_services = _runtime._runtime_services
        _runtime._runtime_config = services.config
        _runtime._runtime_services = services
        try:
            yield services
        finally:
            replaced = _runtime._runtime_services is not services
            _runtime._runtime_config = previous_config
            _runtime._runtime_services = previous_services
            if replaced:
                raise RuntimeError(
                    "application runtime binding was replaced during composition"
                )


__all__ = ["bind_application_runtime"]
