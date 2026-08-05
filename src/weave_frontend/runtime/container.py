"""Typed process runtime with deterministic shared-service lifecycle."""

from __future__ import annotations

import atexit
import hashlib
import json
import os
from collections import namedtuple
from collections.abc import Callable, Iterable
from contextvars import ContextVar, Token
from functools import wraps
from threading import RLock
from typing import Any, TypeVar, cast

from ..compiler import WeavecValidator
from ..verified_workspace import SExpressionWorkspace
from .config import RuntimeConfig
from .publication import CompilerBridge

WorkspaceFactory = Callable[[RuntimeConfig], Any]
CompilerBridgeFactory = Callable[[Any, RuntimeConfig], Any]
ServiceValue = TypeVar("ServiceValue")
CacheInfo = namedtuple("CacheInfo", "hits misses maxsize currsize")
RUNTIME_SERVICE_GRAPH_FORMAT = "weave-jacquard-runtime-service-graph-v1"


class RuntimeClosedError(RuntimeError):
    """Raised when a closed runtime container is used again."""


class RuntimeServiceCycleError(RuntimeError):
    """Raised when runtime service dependencies contain a cycle."""


_declaration_lock = RLock()
_runtime_service_declarations: dict[str, tuple[str, frozenset[str]]] = {}


def _factory_origin(factory: Callable[..., Any]) -> str:
    module = getattr(factory, "__module__", None)
    qualname = getattr(factory, "__qualname__", None)
    if not isinstance(module, str) or not isinstance(qualname, str):
        raise TypeError("runtime service factory must expose module and qualname")
    return f"{module}.{qualname}"


def _validate_service_name(name: str) -> str:
    if not isinstance(name, str) or not name:
        raise ValueError("runtime service name must be a non-empty string")
    return name


def _register_runtime_service(
    name: str,
    origin: str,
    dependencies: Iterable[str],
) -> None:
    service_name = _validate_service_name(name)
    dependency_names = frozenset(_validate_service_name(dependency) for dependency in dependencies)
    with _declaration_lock:
        previous = _runtime_service_declarations.get(service_name)
        if previous is not None and previous[0] != origin:
            raise RuntimeError(
                f"runtime service {service_name!r} was declared by both "
                f"{previous[0]!r} and {origin!r}"
            )
        combined = dependency_names
        if previous is not None:
            combined = previous[1] | dependency_names
        _runtime_service_declarations[service_name] = (origin, combined)


def _registered_runtime_services() -> dict[str, tuple[str, frozenset[str]]]:
    with _declaration_lock:
        return dict(_runtime_service_declarations)


class RuntimeServices:
    """Own lazily created process services under one immutable configuration."""

    def __init__(
        self,
        config: RuntimeConfig,
        *,
        workspace_factory: WorkspaceFactory | None = None,
        compiler_bridge_factory: CompilerBridgeFactory | None = None,
    ) -> None:
        self.config = config
        self._workspace_factory = workspace_factory or self._default_workspace
        self._compiler_bridge_factory = compiler_bridge_factory or self._default_compiler_bridge
        self._services: dict[str, Any] = {}
        self._service_origins: dict[str, str] = {}
        self._service_dependencies: dict[str, set[str]] = {}
        self._service_order: list[str] = []
        self._construction_stack: list[str] = []
        self._service_hits: dict[str, int] = {}
        self._service_misses: dict[str, int] = {}
        self._closed = False
        self._lock = RLock()
        self._declare_service(
            "workspace",
            _factory_origin(self._workspace_factory),
            (),
        )
        self._declare_service(
            "compiler_bridge",
            _factory_origin(self._compiler_bridge_factory),
            ("workspace",),
        )

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def workspace_initialized(self) -> bool:
        return self.service_initialized("workspace")

    @property
    def compiler_bridge_initialized(self) -> bool:
        return self.service_initialized("compiler_bridge")

    def service_initialized(self, name: str) -> bool:
        """Return whether one named runtime service has been materialized."""

        with self._lock:
            return name in self._services

    def workspace(self) -> Any:
        """Return the one race-safe workspace owned by this runtime."""

        return self.service(
            "workspace",
            lambda: self._workspace_factory(self.config),
            origin=_factory_origin(self._workspace_factory),
        )

    def compiler_bridge(self) -> Any:
        """Return the one quota-capable compiler bridge owned by this runtime."""

        return self.service(
            "compiler_bridge",
            lambda: self._compiler_bridge_factory(self.workspace(), self.config),
            depends_on=("workspace",),
            origin=_factory_origin(self._compiler_bridge_factory),
        )

    def service(
        self,
        name: str,
        factory: Callable[[], ServiceValue],
        *,
        depends_on: Iterable[str] = (),
        origin: str | None = None,
    ) -> ServiceValue:
        """Return one lazy named service and record its deterministic dependencies."""

        service_name = _validate_service_name(name)
        dependencies = tuple(_validate_service_name(dependency) for dependency in depends_on)
        factory_origin = origin or _factory_origin(factory)
        with self._lock:
            self._require_open()
            self._record_parent_dependency(service_name)
            self._declare_service(service_name, factory_origin, dependencies)
            if service_name in self._services:
                self._service_hits[service_name] = self._service_hits.get(service_name, 0) + 1
                return cast(ServiceValue, self._services[service_name])
            if service_name in self._construction_stack:
                cycle = [*self._construction_stack, service_name]
                raise RuntimeServiceCycleError(
                    "runtime service dependency cycle: " + " -> ".join(cycle)
                )

            self._service_misses[service_name] = self._service_misses.get(service_name, 0) + 1
            self._construction_stack.append(service_name)
            try:
                value = factory()
            finally:
                popped = self._construction_stack.pop()
                if popped != service_name:
                    raise RuntimeError("runtime service construction stack was corrupted")
            self._services[service_name] = value
            self._service_order.append(service_name)
            return value

    def clear_service(self, name: str, *, include_dependents: bool = True) -> None:
        """Discard one service and optionally every realized dependent service."""

        service_name = _validate_service_name(name)
        with self._lock:
            self._require_open()
            selected = {service_name}
            if include_dependents:
                changed = True
                while changed:
                    changed = False
                    for candidate, dependencies in self._service_dependencies.items():
                        if candidate not in selected and dependencies & selected:
                            selected.add(candidate)
                            changed = True
            close_values = self._remove_services(selected)
        self._close_values(close_values)

    def clear_compiler_bridge(self) -> None:
        """Discard the compiler bridge and every realized dependent service."""

        self.clear_service("compiler_bridge", include_dependents=True)

    def cache_info(self, name: str) -> CacheInfo:
        """Return compatibility cache evidence for one runtime-owned service."""

        service_name = _validate_service_name(name)
        with self._lock:
            return CacheInfo(
                self._service_hits.get(service_name, 0),
                self._service_misses.get(service_name, 0),
                1,
                int(service_name in self._services),
            )

    def service_manifest(self, *, include_state: bool = True) -> dict[str, Any]:
        """Return path-free content-derived service composition evidence."""

        declarations = _registered_runtime_services()
        with self._lock:
            for name, origin in self._service_origins.items():
                registered = declarations.get(name)
                dependencies = frozenset(self._service_dependencies.get(name, set()))
                if registered is not None and registered[0] != origin:
                    raise RuntimeError(
                        f"runtime service {name!r} declaration origin disagrees with "
                        "the process registry"
                    )
                if registered is not None:
                    dependencies |= registered[1]
                declarations[name] = (origin, dependencies)
            services = [
                {
                    "name": name,
                    "origin": declarations[name][0],
                    "depends_on": sorted(declarations[name][1]),
                }
                for name in sorted(declarations)
            ]
            initialized = sorted(self._services)

        payload = {
            "format": RUNTIME_SERVICE_GRAPH_FORMAT,
            "service_count": len(services),
            "services": services,
        }
        result: dict[str, Any] = {
            **payload,
            "service_graph_id": self._hash_json(payload),
        }
        if include_state:
            result.update(
                {
                    "initialized_service_count": len(initialized),
                    "initialized_services": initialized,
                }
            )
        return result

    def close(self) -> None:
        """Close owned resources once in reverse dependency order."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            close_values = self._remove_services(set(self._services))
        self._close_values(close_values)

    def _record_parent_dependency(self, service_name: str) -> None:
        if not self._construction_stack:
            return
        parent = self._construction_stack[-1]
        if parent != service_name:
            self._service_dependencies.setdefault(parent, set()).add(service_name)

    def _declare_service(
        self,
        name: str,
        origin: str,
        dependencies: Iterable[str],
    ) -> None:
        previous_origin = self._service_origins.get(name)
        if previous_origin is not None and previous_origin != origin:
            raise RuntimeError(
                f"runtime service {name!r} was declared by both {previous_origin!r} and {origin!r}"
            )
        self._service_origins[name] = origin
        declared = self._service_dependencies.setdefault(name, set())
        declared.update(dependencies)

    def _remove_services(self, names: set[str]) -> list[Any]:
        close_values: list[Any] = []
        selected = names & self._services.keys()
        for name in self._dependency_close_order(selected):
            value = self._services.pop(name, None)
            if value is not None:
                close_values.append(value)
        self._service_order = [name for name in self._service_order if name not in selected]
        for name in names:
            self._service_hits.pop(name, None)
            self._service_misses.pop(name, None)
        return close_values

    def _dependency_close_order(self, names: set[str]) -> list[str]:
        if not names:
            return []
        reverse_dependencies: dict[str, set[str]] = {name: set() for name in names}
        for dependent in names:
            for dependency in self._service_dependencies.get(dependent, set()):
                if dependency in names:
                    reverse_dependencies[dependency].add(dependent)

        order_index = {name: index for index, name in enumerate(self._service_order)}
        result: list[str] = []
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(name: str) -> None:
            if name in visited:
                return
            if name in visiting:
                raise RuntimeServiceCycleError("runtime service dependency graph contains a cycle")
            visiting.add(name)
            for dependent in sorted(
                reverse_dependencies[name],
                key=lambda item: (-order_index.get(item, -1), item),
            ):
                visit(dependent)
            visiting.remove(name)
            visited.add(name)
            result.append(name)

        for name in sorted(
            names,
            key=lambda item: (-order_index.get(item, -1), item),
        ):
            visit(name)
        return result

    @staticmethod
    def _close_values(values: Iterable[Any]) -> None:
        seen: set[int] = set()
        first_error: Exception | None = None
        for value in values:
            identity = id(value)
            if identity in seen:
                continue
            seen.add(identity)
            close = getattr(value, "close", None)
            if not callable(close):
                continue
            try:
                close()
            except Exception as exc:  # pragma: no cover - defensive shutdown path
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeClosedError("Jacquard runtime services are closed")

    @staticmethod
    def _hash_json(value: Any) -> str:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

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
_bound_runtime_services: ContextVar[RuntimeServices | None] = ContextVar(
    "weave_bound_runtime_services",
    default=None,
)


def _bound_runtime() -> RuntimeServices | None:
    services = _bound_runtime_services.get()
    if services is not None and services.closed:
        raise RuntimeClosedError("bound Jacquard runtime services are closed")
    return services


def _bind_runtime_services(
    services: RuntimeServices,
) -> Token[RuntimeServices | None]:
    if not isinstance(services, RuntimeServices):
        raise TypeError("services must be a RuntimeServices instance")
    if services.closed:
        raise RuntimeClosedError("cannot bind a closed runtime container")
    return _bound_runtime_services.set(services)


def _reset_bound_runtime_services(
    token: Token[RuntimeServices | None],
) -> None:
    _bound_runtime_services.reset(token)


def runtime_config() -> RuntimeConfig:
    """Return the immutable configuration snapshot for the current runtime."""

    bound = _bound_runtime()
    if bound is not None:
        return bound.config

    global _runtime_config
    with _runtime_lock:
        if _runtime_config is None:
            _runtime_config = RuntimeConfig.from_environ(os.environ)
        return _runtime_config


def runtime_services() -> RuntimeServices:
    """Return the task-local runtime or the process-wide default container."""

    bound = _bound_runtime()
    if bound is not None:
        return bound

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
    """Close and forget the process runtime, optionally pinning replacement config."""

    global _runtime_config, _runtime_services
    with _runtime_lock:
        previous = _runtime_services
        _runtime_services = None
        _runtime_config = config
    if previous is not None:
        previous.close()


def close_runtime_services() -> None:
    """Close the process runtime and clear its immutable configuration snapshot."""

    reset_runtime_services()


def clear_runtime_service(name: str) -> None:
    """Discard one named service from the selected runtime when it exists."""

    bound = _bound_runtime()
    if bound is not None:
        bound.clear_service(name)
        return

    with _runtime_lock:
        services = _runtime_services
    if services is not None and not services.closed:
        services.clear_service(name)


def clear_runtime_compiler_bridge() -> None:
    """Discard the compiler bridge from the selected runtime when it exists."""

    clear_runtime_service("compiler_bridge")


def runtime_service_cache_info(name: str) -> CacheInfo:
    """Return cache evidence without constructing a process runtime."""

    bound = _bound_runtime()
    if bound is not None:
        return bound.cache_info(name)

    with _runtime_lock:
        services = _runtime_services
    if services is None or services.closed:
        return CacheInfo(0, 0, 1, 0)
    return services.cache_info(name)


def runtime_service(
    name: str,
    *,
    depends_on: Iterable[str] = (),
) -> Callable[[Callable[[], ServiceValue]], Callable[[], ServiceValue]]:
    """Decorate a no-argument factory as one selected-runtime lazy service."""

    service_name = _validate_service_name(name)
    dependency_names = tuple(_validate_service_name(dependency) for dependency in depends_on)

    def decorate(factory: Callable[[], ServiceValue]) -> Callable[[], ServiceValue]:
        origin = _factory_origin(factory)
        _register_runtime_service(service_name, origin, dependency_names)

        @wraps(factory)
        def wrapped() -> ServiceValue:
            return runtime_services().service(
                service_name,
                factory,
                depends_on=dependency_names,
                origin=origin,
            )

        wrapped.cache_clear = (  # type: ignore[attr-defined]
            lambda: clear_runtime_service(service_name)
        )
        wrapped.cache_info = (  # type: ignore[attr-defined]
            lambda: runtime_service_cache_info(service_name)
        )
        wrapped.runtime_service_name = service_name  # type: ignore[attr-defined]
        return wrapped

    return decorate


def workspace_cache_info() -> CacheInfo:
    """Compatibility cache evidence for the historical workspace factory."""

    return runtime_service_cache_info("workspace")


def compiler_bridge_cache_info() -> CacheInfo:
    """Compatibility cache evidence for the historical compiler factory."""

    return runtime_service_cache_info("compiler_bridge")


atexit.register(close_runtime_services)


__all__ = [
    "RUNTIME_SERVICE_GRAPH_FORMAT",
    "RuntimeClosedError",
    "RuntimeServiceCycleError",
    "RuntimeServices",
    "clear_runtime_compiler_bridge",
    "clear_runtime_service",
    "close_runtime_services",
    "compiler_bridge_cache_info",
    "install_runtime_services",
    "reset_runtime_services",
    "runtime_config",
    "runtime_service",
    "runtime_service_cache_info",
    "runtime_services",
    "workspace_cache_info",
]
