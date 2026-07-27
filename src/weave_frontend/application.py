"""Explicit production application composition for Jacquard's MCP surface."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .mcp_capabilities import (
    PUBLIC_CAPABILITIES,
    Capability,
    ModuleLoader,
    install_public_capabilities,
)

APPLICATION_MANIFEST_FORMAT = "weave-jacquard-application-v1"
TOOL_MANIFEST_FORMAT = "weave-jacquard-tool-manifest-v1"
PUBLIC_CONFIGURATION_VARIABLES = (
    "WEAVE_DB_PATH",
    "WEAVE_BUILD_ROOT",
    "WEAVEC_BIN",
    "WEAVEC_SOURCE_ROOT",
    "WEAVE_BWRAP",
)
_REQUIRED_PUBLIC_TOOLS = frozenset(
    {
        "weave_help",
        "project_initialize",
        "program_validate",
        "branch_merge",
    }
)


class ApplicationCompositionError(RuntimeError):
    """Raised when the public MCP application cannot be composed deterministically."""


@dataclass(frozen=True)
class JacquardApp:
    """One validated production server plus its immutable public composition metadata.

    Existing MCP modules still register decorated tools on the shared server while the
    migration to pure capability factories proceeds. This object is the explicit final
    composition boundary: it installs the declared capability graph once, validates the
    resulting public tool registry, and exposes content-derived manifests for tests,
    documentation, and startup diagnostics.
    """

    server: Any
    capability_manifest: tuple[dict[str, Any], ...]
    tool_manifest: dict[str, Any]
    application_manifest: dict[str, Any]

    @classmethod
    def compose(
        cls,
        server: Any,
        *,
        capabilities: Iterable[Capability] = PUBLIC_CAPABILITIES,
        module_loader: ModuleLoader | None = None,
        required_tools: Iterable[str] = _REQUIRED_PUBLIC_TOOLS,
    ) -> JacquardApp:
        """Install and validate one complete public Jacquard MCP application."""

        install_arguments: dict[str, Any] = {"capabilities": capabilities}
        if module_loader is not None:
            install_arguments["module_loader"] = module_loader
        capability_manifest = install_public_capabilities(server, **install_arguments)
        tool_manifest = build_tool_manifest(
            registered_tool_names(server),
            required_tools=required_tools,
        )
        payload = {
            "format": APPLICATION_MANIFEST_FORMAT,
            "capabilities": [dict(item) for item in capability_manifest],
            "tool_manifest_id": tool_manifest["tool_manifest_id"],
            "tool_count": tool_manifest["tool_count"],
            "configuration_variables": list(PUBLIC_CONFIGURATION_VARIABLES),
        }
        application_manifest = {
            **payload,
            "application_id": _hash_json(payload),
        }
        return cls(
            server=server,
            capability_manifest=capability_manifest,
            tool_manifest=tool_manifest,
            application_manifest=application_manifest,
        )


def registered_tool_names(server: Any) -> tuple[str, ...]:
    """Return deterministic tool names from the supported FastMCP registry shapes."""

    manager = getattr(server, "_tool_manager", None)
    registries = (
        getattr(manager, "_tools", None),
        getattr(server, "tools", None),
    )
    registry = next((item for item in registries if isinstance(item, Mapping)), None)
    if registry is None:
        raise ApplicationCompositionError(
            "FastMCP tool registry is unavailable; public application composition "
            "requires a mapping-backed tool manager"
        )

    names = tuple(sorted(str(name) for name in registry))
    if not names:
        raise ApplicationCompositionError("public MCP application registered no tools")
    if any(not name for name in names):
        raise ApplicationCompositionError("public MCP tool names must be non-empty")
    if len(names) != len(set(names)):
        raise ApplicationCompositionError("public MCP tool names must be unique")
    return names


def build_tool_manifest(
    tool_names: Iterable[str],
    *,
    required_tools: Iterable[str] = _REQUIRED_PUBLIC_TOOLS,
) -> dict[str, Any]:
    """Build a content-derived manifest for one exact public tool-name set."""

    raw_names = tuple(tool_names)
    if not raw_names or any(
        not isinstance(name, str) or not name for name in raw_names
    ):
        raise ApplicationCompositionError("tool manifest requires non-empty string names")
    names = tuple(sorted(raw_names))
    if len(names) != len(set(names)):
        raise ApplicationCompositionError("tool manifest contains duplicate names")

    required = frozenset(required_tools)
    if any(not isinstance(name, str) or not name for name in required):
        raise ApplicationCompositionError("required tool names must be non-empty strings")
    missing = sorted(required.difference(names))
    if missing:
        raise ApplicationCompositionError(
            f"public MCP application is missing required tools {missing!r}"
        )

    payload = {
        "format": TOOL_MANIFEST_FORMAT,
        "tool_count": len(names),
        "tools": list(names),
    }
    return {
        **payload,
        "tool_manifest_id": _hash_json(payload),
    }


def _hash_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "APPLICATION_MANIFEST_FORMAT",
    "PUBLIC_CONFIGURATION_VARIABLES",
    "TOOL_MANIFEST_FORMAT",
    "ApplicationCompositionError",
    "JacquardApp",
    "build_tool_manifest",
    "registered_tool_names",
]
