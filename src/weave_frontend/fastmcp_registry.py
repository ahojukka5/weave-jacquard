"""FastMCP registry compatibility for deterministic application composition."""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

ToolTransform = Callable[[str, Any], Any]


class FastMCPRegistryError(RuntimeError):
    """Raised when a supported FastMCP registry contract cannot be extracted."""


@dataclass(frozen=True)
class FastMCPRegistryAdapter:
    """Capture one supported FastMCP tool registry and its public contracts."""

    server: Any

    def tool_names(self) -> tuple[str, ...]:
        """Return deterministic tool names from one captured registry snapshot."""

        return tuple(sorted(self._snapshot()))

    def tool_contracts(self) -> tuple[dict[str, Any], ...]:
        """Return caller-visible contracts from one captured registry snapshot."""

        registry = self._snapshot()
        return tuple(
            self._tool_contract(name, registry[name])
            for name in sorted(registry)
        )

    def tool_objects(self) -> Mapping[str, Any]:
        """Return an immutable exact-object snapshot of the registered tools."""

        return MappingProxyType(self._snapshot())

    def replace_tools_from(
        self,
        source_server: Any,
        *,
        transform: ToolTransform | None = None,
    ) -> tuple[str, ...]:
        """Replace this registry with verified tools from another server."""

        source = FastMCPRegistryAdapter(source_server)
        source_registry = source._registry()
        source_snapshot = source._snapshot()
        source_contracts = source.tool_contracts()
        names = tuple(sorted(source_snapshot))
        replacement = {
            name: (
                transform(name, source_snapshot[name])
                if transform is not None
                else source_snapshot[name]
            )
            for name in names
        }
        replacement_contracts = tuple(
            self._tool_contract(name, replacement[name])
            for name in names
        )
        if replacement_contracts != source_contracts:
            raise FastMCPRegistryError(
                "FastMCP tool transformation changed canonical tool contracts"
            )

        target_registry = self._mutable_registry()
        if target_registry is source_registry and transform is None:
            return names

        previous = dict(target_registry.items())
        try:
            target_registry.clear()
            target_registry.update(replacement)
            installed = self._snapshot()
            if set(installed) != set(replacement):
                raise FastMCPRegistryError(
                    "FastMCP target registry did not preserve the complete tool set"
                )
            if any(installed[name] is not replacement[name] for name in names):
                raise FastMCPRegistryError(
                    "FastMCP target registry did not preserve replacement tool objects"
                )
            installed_contracts = tuple(
                self._tool_contract(name, installed[name])
                for name in names
            )
            if installed_contracts != source_contracts:
                raise FastMCPRegistryError(
                    "FastMCP target registry changed canonical tool contracts"
                )
        except Exception as exc:
            try:
                target_registry.clear()
                target_registry.update(previous)
            except Exception as rollback_exc:
                raise FastMCPRegistryError(
                    "FastMCP tool registry replacement and rollback both failed"
                ) from rollback_exc
            if isinstance(exc, FastMCPRegistryError):
                raise
            raise FastMCPRegistryError(
                "FastMCP tool registry replacement failed"
            ) from exc
        return names

    def _registry(self) -> Mapping[Any, Any]:
        manager = getattr(self.server, "_tool_manager", None)
        registries = (
            getattr(manager, "_tools", None),
            getattr(self.server, "tools", None),
        )
        registry = next(
            (item for item in registries if isinstance(item, Mapping)),
            None,
        )
        if registry is None:
            raise FastMCPRegistryError(
                "FastMCP tool registry is unavailable; public application "
                "composition requires a mapping-backed tool manager"
            )
        return registry

    def _mutable_registry(self) -> MutableMapping[Any, Any]:
        registry = self._registry()
        if not isinstance(registry, MutableMapping):
            raise FastMCPRegistryError(
                "FastMCP target tool registry must be mutable for application "
                "registration"
            )
        return registry

    def _snapshot(self) -> dict[str, Any]:
        items = tuple(self._registry().items())
        if not items:
            raise FastMCPRegistryError("public MCP application registered no tools")

        snapshot: dict[str, Any] = {}
        for name, tool in items:
            if not isinstance(name, str) or not name:
                raise FastMCPRegistryError(
                    "public MCP tool registry keys must be non-empty strings"
                )
            if name in snapshot:
                raise FastMCPRegistryError("public MCP tool names must be unique")
            snapshot[name] = tool
        return snapshot

    @staticmethod
    def _tool_contract(registry_name: str, tool: Any) -> dict[str, Any]:
        declared_name = getattr(tool, "name", registry_name)
        if declared_name != registry_name:
            raise FastMCPRegistryError(
                f"registered tool name {registry_name!r} disagrees with metadata "
                f"{declared_name!r}"
            )

        parameters = getattr(tool, "parameters", None)
        if not isinstance(parameters, Mapping):
            raise FastMCPRegistryError(
                f"registered tool {registry_name!r} has no mapping input schema"
            )
        fn_metadata = getattr(tool, "fn_metadata", None)
        output_schema = getattr(tool, "output_schema", None)
        if output_schema is None and fn_metadata is not None:
            output_schema = getattr(fn_metadata, "output_schema", None)
        if output_schema is not None and not isinstance(output_schema, Mapping):
            raise FastMCPRegistryError(
                f"registered tool {registry_name!r} has a non-mapping output schema"
            )

        metadata = getattr(tool, "meta", None)
        if metadata is None:
            metadata = getattr(tool, "_meta", None)
        return {
            "name": registry_name,
            "title": getattr(tool, "title", None),
            "description": getattr(tool, "description", None),
            "input_schema": parameters,
            "output_schema": output_schema,
            "annotations": getattr(tool, "annotations", None),
            "icons": getattr(tool, "icons", None),
            "meta": metadata,
        }


__all__ = [
    "FastMCPRegistryAdapter",
    "FastMCPRegistryError",
    "ToolTransform",
]
