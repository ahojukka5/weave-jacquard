"""Typed process runtime with deterministic shared-service lifecycle."""

from __future__ import annotations

import atexit
import os
from collections import namedtuple
from collections.abc import Callable
from threading import RLock
from typing import Any

from .concurrent_workspace import SExpressionWorkspace
from .quota_aware_compiler_bridge import CompilerBridge
from .runtime_config import RuntimeConfig
from .weavec import WeavecValidator

WorkspaceFactory = Callable[[RuntimeConfig], Any]
CompilerBridgeFactory = Callable[[Any, RuntimeConfig], Any]
CacheInfo = namedtuple("CacheInfo", "hits misses maxsize currsize")


class RuntimeClosedError(RuntimeError):
    """Raised when a closed runtime container is used again."""


class RuntimeServices:
    """Own lazily created process-wide services under one immutable configuration."""

    def __init__(
        self,
        config: RuntimeConfig,
        *,
        workspace_factory: WorkspaceFactory | None = None,
        compiler_bridge_factory: CompilerBridgeFactory | None = None,
    ) -> None:
        self.config = config
        self._workspace_factory = workspace_factory or self._default_workspace
        self._compiler_bridge_factory = (
            compiler_bridge_factory or self._default_compiler_bridge
        )
        self._workspace: Any | None = None
        self._compiler_bridge: Any | None = None
        self._closed = False
        self._lock = RLock()

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def workspace_initialized(self) -> bool:
        with self._lock:
            return self._workspace is not None

    @property
    def compiler_bridge_initialized(self) -> bool:
        with self._lock:
            return self._compiler_bridge is not None

    def workspace(self) -> Any:
        """Return the one race-safe workspace owned by this runtime."""

        with self._lock:
            self._require_open()
            if self._workspace is None:
                self._workspace = self._workspace_factory(self.config)
            return self._workspace

    def compiler_bridge(self) -> Any:
        """Return the one quota-capable compiler bridge owned by this runtime."""

        with self._lock:
            self._require_open()
            if self._compiler_bridge is None:
                self._compiler_bridge = self._compiler_bridge_factory(
                    self.workspace(),
                    self.config,
                )
            return self._compiler_bridge

    def clear_compiler_bridge(self) -> None:
        """Discard the stateless bridge while retaining the shared workspace."""

        with self._lock:
            self._require_open()
            self._compiler_bridge = None

    def close(self) -> None:
        """Close owned resources exactly once and reject later service access."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            workspace = self._workspace
            self._compiler_bridge = None
            self._workspace = None
        if workspace is not None:
            workspace.close()

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeClosedError("Jacquard runtime services are closed")

    @staticmethod
    def _default_workspace(config: RuntimeConfig) -> SExpressionWorkspace:
        workspace = SExpressionWorkspace(
            config.database_path,
            weavec_source_root=config.weavec_source_root,
            weavec_binary=config.weavec_binary,
        )
        workspace.validator = WeavecValidator(
            config.weavec_binary,
            config.weavec_source_root,
            environment_fallback=False,
        )
        return workspace

    @staticmethod
    def _default_compiler_bridge(
        workspace: Any,
        config: RuntimeConfig,
    ) -> CompilerBridge:
        bridge = CompilerBridge(
            workspace,
            compiler=config.weavec_binary,
            build_root=config.build_root,
        )
        bridge._environment_fallback = False
        return bridge


_runtime_lock = RLock()
_runtime_config: RuntimeConfig | None = None
_runtime_services: RuntimeServices | None = None


def runtime_config() -> RuntimeConfig:
    """Return the immutable configuration snapshot for the current runtime."""

    global _runtime_config
    with _runtime_lock:
        if _runtime_config is None:
            _runtime_config = RuntimeConfig.from_environ(os.environ)
        return _runtime_config


def runtime_services() -> RuntimeServices:
    """Return the process-wide typed service container."""

    global _runtime_services
    with _runtime_lock:
        if _runtime_services is None:
            _runtime_services = RuntimeServices(runtime_config())
        return _runtime_services


def install_runtime_services(services: RuntimeServices) -> None:
    """Install an explicit container, closing any earlier process runtime."""

    if not isinstance(services, RuntimeServices):
        raise TypeError("services must be a RuntimeServices instance")
    if services.closed:
        raise RuntimeClosedError("cannot install a closed runtime container")
    global _runtime_config, _runtime_services
    with _runtime_lock:
        previous = _runtime_services
        _runtime_config = services.config
        _runtime_services = services
    if previous is not None and previous is not services:
        previous.close()


def reset_runtime_services(config: RuntimeConfig | None = None) -> None:
    """Close and forget the current runtime, optionally pinning replacement config."""

    global _runtime_config, _runtime_services
    with _runtime_lock:
        previous = _runtime_services
        _runtime_services = None
        _runtime_config = config
    if previous is not None:
        previous.close()


def close_runtime_services() -> None:
    """Close the current runtime and clear its immutable configuration snapshot."""

    reset_runtime_services()


def clear_runtime_compiler_bridge() -> None:
    """Discard only the cached compiler bridge when a runtime already exists."""

    with _runtime_lock:
        services = _runtime_services
    if services is not None and not services.closed:
        services.clear_compiler_bridge()


def workspace_cache_info() -> CacheInfo:
    """Compatibility cache evidence for historical workspace factory tests."""

    with _runtime_lock:
        services = _runtime_services
    current = int(
        services is not None
        and not services.closed
        and services.workspace_initialized
    )
    return CacheInfo(0, 0, 1, current)


def compiler_bridge_cache_info() -> CacheInfo:
    """Compatibility cache evidence for historical compiler factory tests."""

    with _runtime_lock:
        services = _runtime_services
    current = int(
        services is not None
        and not services.closed
        and services.compiler_bridge_initialized
    )
    return CacheInfo(0, 0, 1, current)


atexit.register(close_runtime_services)


__all__ = [
    "RuntimeClosedError",
    "RuntimeServices",
    "clear_runtime_compiler_bridge",
    "close_runtime_services",
    "compiler_bridge_cache_info",
    "install_runtime_services",
    "reset_runtime_services",
    "runtime_config",
    "runtime_services",
    "workspace_cache_info",
]
