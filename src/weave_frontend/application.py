"""Explicit production application composition for Jacquard's MCP surface."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from typing import Any

from .mcp_capabilities import (
    PUBLIC_CAPABILITIES,
    Capability,
    ModuleLoader,
    install_public_capabilities,
)

APPLICATION_MANIFEST_FORMAT = "weave-jacquard-application-v2"
TOOL_MANIFEST_FORMAT = "weave-jacquard-tool-manifest-v2"
PUBLIC_CONFIGURATION_VARIABLES = (
    "WEAVEC_BIN",
    "WEAVEC_SOURCE_ROOT",
    "WEAVE_BUILD_ROOT",
    "WEAVE_BWRAP",
    "WEAVE_DB_PATH",
    "WEAVE_MERGE_ATTESTATION_ROOT",
    "WEAVE_MERGE_BUILD_ROOT",
    "WEAVE_MERGE_TEST_RUN_ROOT",
    "WEAVE_TEST_BATCH_ROOT",
    "WEAVE_TEST_RUN_ROOT",
)
_REQUIRED_PUBLIC_TOOLS = frozenset(
    {
        "weave_help",
        "project_initialize",
        "program_validate",
        "branch_merge",
    }
)
_TOOL_CONTRACT_FIELDS = frozenset(
    {
        "name",
        "title",
        "description",
        "input_schema",
        "output_schema",
        "annotations",
        "icons",
        "meta",
    }
)


class ApplicationCompositionError(RuntimeError):
    """Raised when the public MCP application cannot be composed deterministically."""


@dataclass(frozen=True)
class JacquardApp:
    """One validated production server plus its public composition snapshots."""

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
            registered_tool_contracts(server),
            required_tools=required_tools,
        )
        configuration_variables = _canonical_names(
            PUBLIC_CONFIGURATION_VARIABLES,
            subject="configuration variable",
        )
        payload = {
            "format": APPLICATION_MANIFEST_FORMAT,
            "capabilities": [dict(item) for item in capability_manifest],
            "tool_manifest_id": tool_manifest["tool_manifest_id"],
            "tool_count": tool_manifest["tool_count"],
            "configuration_variables": list(configuration_variables),
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
    """Return deterministic tool names from one captured FastMCP registry."""

    return tuple(sorted(_tool_registry_snapshot(server)))


def registered_tool_contracts(server: Any) -> tuple[dict[str, Any], ...]:
    """Return canonical MCP contracts from one captured FastMCP registry."""

    registry = _tool_registry_snapshot(server)
    return tuple(
        _registered_tool_contract(name, registry[name])
        for name in sorted(registry)
    )


def build_tool_manifest(
    tool_contracts: Iterable[Mapping[str, Any]],
    *,
    required_tools: Iterable[str] = _REQUIRED_PUBLIC_TOOLS,
) -> dict[str, Any]:
    """Build a content-derived manifest for one exact public MCP contract set."""

    raw_contracts = tuple(tool_contracts)
    if not raw_contracts:
        raise ApplicationCompositionError("tool manifest requires at least one contract")

    contracts = tuple(
        sorted(
            (_manifest_contract(contract) for contract in raw_contracts),
            key=lambda contract: str(contract["name"]),
        )
    )
    names = tuple(str(contract["name"]) for contract in contracts)
    if len(names) != len(set(names)):
        raise ApplicationCompositionError("tool manifest contains duplicate names")

    raw_required = tuple(required_tools)
    if any(not isinstance(name, str) or not name for name in raw_required):
        raise ApplicationCompositionError("required tool names must be non-empty strings")
    required = frozenset(raw_required)
    missing = sorted(required.difference(names))
    if missing:
        raise ApplicationCompositionError(
            f"public MCP application is missing required tools {missing!r}"
        )

    payload = {
        "format": TOOL_MANIFEST_FORMAT,
        "tool_count": len(contracts),
        "tool_names": list(names),
        "tools": list(contracts),
    }
    return {
        **payload,
        "tool_manifest_id": _hash_json(payload),
    }


def _tool_registry(server: Any) -> Mapping[Any, Any]:
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
    return registry


def _tool_registry_snapshot(server: Any) -> dict[str, Any]:
    registry = _tool_registry(server)
    items = tuple(registry.items())
    if not items:
        raise ApplicationCompositionError("public MCP application registered no tools")

    snapshot: dict[str, Any] = {}
    for name, tool in items:
        if not isinstance(name, str) or not name:
            raise ApplicationCompositionError(
                "public MCP tool registry keys must be non-empty strings"
            )
        if name in snapshot:
            raise ApplicationCompositionError("public MCP tool names must be unique")
        snapshot[name] = tool
    return snapshot


def _registered_tool_contract(registry_name: str, tool: Any) -> dict[str, Any]:
    declared_name = getattr(tool, "name", registry_name)
    if declared_name != registry_name:
        raise ApplicationCompositionError(
            f"registered tool name {registry_name!r} disagrees with metadata {declared_name!r}"
        )

    parameters = getattr(tool, "parameters", None)
    if not isinstance(parameters, Mapping):
        raise ApplicationCompositionError(
            f"registered tool {registry_name!r} has no mapping input schema"
        )
    fn_metadata = getattr(tool, "fn_metadata", None)
    output_schema = getattr(tool, "output_schema", None)
    if output_schema is None and fn_metadata is not None:
        output_schema = getattr(fn_metadata, "output_schema", None)
    if output_schema is not None and not isinstance(output_schema, Mapping):
        raise ApplicationCompositionError(
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


def _manifest_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
    keys = tuple(contract.keys())
    if any(not isinstance(key, str) for key in keys):
        raise ApplicationCompositionError("tool contract keys must be strings")
    unknown = sorted(set(keys).difference(_TOOL_CONTRACT_FIELDS))
    if unknown:
        raise ApplicationCompositionError(
            f"tool contract contains unsupported fields {unknown!r}"
        )

    name = contract.get("name")
    if not isinstance(name, str) or not name:
        raise ApplicationCompositionError("tool contract name must be a non-empty string")
    input_schema = contract.get("input_schema")
    if not isinstance(input_schema, Mapping):
        raise ApplicationCompositionError(
            f"tool contract {name!r} requires a mapping input_schema"
        )
    output_schema = contract.get("output_schema")
    if output_schema is not None and not isinstance(output_schema, Mapping):
        raise ApplicationCompositionError(
            f"tool contract {name!r} output_schema must be a mapping or null"
        )

    payload = {
        "name": name,
        "title": _optional_string(contract.get("title"), field="title", tool=name),
        "description": _optional_string(
            contract.get("description"),
            field="description",
            tool=name,
        ),
        "input_schema": _json_ready(input_schema, path=f"{name}.input_schema"),
        "output_schema": _json_ready(
            output_schema,
            path=f"{name}.output_schema",
        ),
        "annotations": _json_ready(
            contract.get("annotations"),
            path=f"{name}.annotations",
        ),
        "icons": _json_ready(contract.get("icons"), path=f"{name}.icons"),
        "meta": _json_ready(contract.get("meta"), path=f"{name}.meta"),
    }
    return {
        **payload,
        "tool_contract_id": _hash_json(payload),
    }


def _optional_string(value: Any, *, field: str, tool: str) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise ApplicationCompositionError(
        f"tool contract {tool!r} {field} must be a string or null"
    )


def _json_ready(value: Any, *, path: str) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ApplicationCompositionError(f"non-finite number in tool contract at {path}")
        return value
    if isinstance(value, Enum):
        return _json_ready(value.value, path=path)

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump(mode="json", by_alias=True, exclude_none=True)
        except Exception as exc:
            raise ApplicationCompositionError(
                f"cannot serialize tool contract value at {path}: {exc}"
            ) from exc
        return _json_ready(dumped, path=path)
    if is_dataclass(value):
        return _json_ready(asdict(value), path=path)
    if isinstance(value, Mapping):
        keys = tuple(value.keys())
        if any(not isinstance(key, str) for key in keys):
            raise ApplicationCompositionError(
                f"non-string mapping key in tool contract at {path}"
            )
        return {
            key: _json_ready(value[key], path=f"{path}.{key}")
            for key in sorted(keys)
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [
            _json_ready(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    raise ApplicationCompositionError(
        f"unsupported tool contract value {type(value).__name__} at {path}"
    )


def _canonical_names(values: Iterable[str], *, subject: str) -> tuple[str, ...]:
    raw = tuple(values)
    if not raw or any(not isinstance(value, str) or not value for value in raw):
        raise ApplicationCompositionError(
            f"{subject} names must be non-empty strings"
        )
    names = tuple(sorted(raw))
    if len(names) != len(set(names)):
        raise ApplicationCompositionError(f"{subject} names must be unique")
    return names


def _hash_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "APPLICATION_MANIFEST_FORMAT",
    "PUBLIC_CONFIGURATION_VARIABLES",
    "TOOL_MANIFEST_FORMAT",
    "ApplicationCompositionError",
    "JacquardApp",
    "build_tool_manifest",
    "registered_tool_contracts",
    "registered_tool_names",
]
