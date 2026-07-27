from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from weave_frontend.application import (
    APPLICATION_MANIFEST_FORMAT,
    TOOL_MANIFEST_FORMAT,
    ApplicationCompositionError,
    JacquardApp,
    build_tool_manifest,
    registered_tool_names,
)
from weave_frontend.mcp_capabilities import Capability, capability_manifest


@dataclass
class _LowLevelServer:
    instructions: str = "legacy"


class _FakeFastMCP:
    def __init__(self, tools: dict[str, Any] | None = None) -> None:
        self._mcp_server = _LowLevelServer()
        self.tools = dict(tools or {})
        self.removed: list[str] = []
        self.added: list[str] = []

    def remove_tool(self, name: str) -> None:
        self.removed.append(name)
        del self.tools[name]

    def add_tool(
        self,
        function: Any,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        del description
        tool_name = name or function.__name__
        self.tools[tool_name] = function
        self.added.append(tool_name)


def _loader(name: str) -> ModuleType:
    if name == "weave_frontend.mcp_tested_merge_attestation_guidance":
        return SimpleNamespace(  # type: ignore[return-value]
            INSTRUCTIONS="composed instructions",
            weave_help=lambda topic="workflow": {"ok": True, "topic": topic},
        )
    return ModuleType(name)


def test_application_composes_capabilities_and_tools_deterministically() -> None:
    capabilities = (
        Capability("base", "example.base"),
        Capability("feature", "example.feature", ("base",)),
    )
    server = _FakeFastMCP(
        {
            "weave_help": object(),
            "project_initialize": object(),
            "program_validate": object(),
            "branch_merge": object(),
            "zeta": object(),
            "alpha": object(),
        }
    )

    app = JacquardApp.compose(
        server,
        capabilities=capabilities,
        module_loader=_loader,
    )

    assert app.server is server
    assert app.capability_manifest == capability_manifest(capabilities)
    assert app.tool_manifest["format"] == TOOL_MANIFEST_FORMAT
    assert app.tool_manifest["tools"] == sorted(server.tools)
    assert app.tool_manifest["tool_count"] == len(server.tools)
    assert len(app.tool_manifest["tool_manifest_id"]) == 64
    assert app.application_manifest["format"] == APPLICATION_MANIFEST_FORMAT
    assert app.application_manifest["tool_manifest_id"] == app.tool_manifest[
        "tool_manifest_id"
    ]
    assert app.application_manifest["capabilities"] == list(app.capability_manifest)
    assert len(app.application_manifest["application_id"]) == 64
    assert server._mcp_server.instructions == "composed instructions"
    assert server.removed == ["weave_help"]
    assert server.added == ["weave_help"]


def test_tool_manifest_identity_is_order_independent() -> None:
    left = build_tool_manifest(
        ["weave_help", "project_initialize", "program_validate", "branch_merge"]
    )
    right = build_tool_manifest(
        ["program_validate", "branch_merge", "weave_help", "project_initialize"]
    )

    assert left == right


def test_missing_required_tool_is_rejected() -> None:
    with pytest.raises(ApplicationCompositionError, match="missing required tools"):
        build_tool_manifest(["weave_help"])


def test_unknown_tool_registry_shape_is_rejected() -> None:
    with pytest.raises(ApplicationCompositionError, match="tool registry is unavailable"):
        registered_tool_names(SimpleNamespace())


def test_public_entrypoint_exposes_one_composed_application() -> None:
    from weave_jacquard import mcp_build as public_entrypoint

    assert public_entrypoint.PUBLIC_APP.server is public_entrypoint.mcp
    assert (
        public_entrypoint.PUBLIC_APP.capability_manifest
        == public_entrypoint.PUBLIC_CAPABILITY_MANIFEST
    )
    assert public_entrypoint.PUBLIC_APP.tool_manifest == public_entrypoint.PUBLIC_TOOL_MANIFEST
    assert (
        public_entrypoint.PUBLIC_APP.application_manifest
        == public_entrypoint.PUBLIC_APPLICATION_MANIFEST
    )
    assert public_entrypoint.PUBLIC_TOOL_MANIFEST["tools"] == sorted(
        public_entrypoint.PUBLIC_TOOL_MANIFEST["tools"]
    )
    assert "weave_help" in public_entrypoint.PUBLIC_TOOL_MANIFEST["tools"]
    assert "tested_merge_attest" in public_entrypoint.PUBLIC_TOOL_MANIFEST["tools"]
