from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from weave_frontend.mcp_capabilities import (
    PUBLIC_CAPABILITIES,
    Capability,
    capability_manifest,
    install_public_capabilities,
    validate_capabilities,
)


@dataclass
class _LowLevelServer:
    instructions: str = "legacy"


class _FakeFastMCP:
    def __init__(self) -> None:
        self._mcp_server = _LowLevelServer()
        self.tools: dict[str, Any] = {"weave_help": object()}
        self.removed: list[str] = []
        self.added: list[str] = []
        self.descriptions: dict[str, str] = {}

    def remove_tool(self, name: str) -> None:
        self.removed.append(name)
        del self.tools[name]

    def add_tool(
        self,
        function: Any,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        tool_name = name or function.__name__
        self.tools[tool_name] = function
        self.added.append(tool_name)
        self.descriptions[tool_name] = description or ""


def test_public_capabilities_have_unique_dependency_order() -> None:
    assert validate_capabilities(PUBLIC_CAPABILITIES) == PUBLIC_CAPABILITIES
    names = [capability.name for capability in PUBLIC_CAPABILITIES]

    assert names[0] == "concurrent_nodes"
    assert names[-1] == "revision_reads"
    assert len(names) == len(set(names))
    assert "test_targets" in names
    assert "test_runs" in names
    assert "test_batches" in names
    assert "test_impact" in names
    assert "merge_test_impact" in names
    assert "merge_candidate_test_execution" in names
    assert "tested_merge_attestations" in names
    assert names.index("concurrent_targets") < names.index("test_targets")
    assert names.index("test_targets") < names.index("test_runs")
    assert names.index("test_runs") < names.index("test_batches")
    assert names.index("test_batches") < names.index("test_impact")
    assert names.index("test_impact") < names.index("merge_test_impact")
    assert names.index("merge_test_impact") < names.index(
        "merge_candidate_test_execution"
    )
    assert names.index("merge_candidate_test_execution") < names.index(
        "tested_merge_attestations"
    )
    assert names.index("tested_merge_attestations") < names.index("policy")
    assert "resume_snapshot" in names
    assert "selected_merge_train_preview" in names


def test_capability_manifest_is_json_ready_and_ordered() -> None:
    manifest = capability_manifest(
        (
            Capability("base", "example.base"),
            Capability("feature", "example.feature", ("base",)),
        )
    )

    assert manifest == (
        {"name": "base", "module": "example.base", "depends_on": []},
        {
            "name": "feature",
            "module": "example.feature",
            "depends_on": ["base"],
        },
    )


@pytest.mark.parametrize(
    ("capabilities", "message"),
    [
        (
            (
                Capability("duplicate", "example.one"),
                Capability("duplicate", "example.two"),
            ),
            "duplicate capability",
        ),
        (
            (Capability("feature", "example.feature", ("base",)),),
            "requires earlier dependencies",
        ),
        ((Capability("", "example.empty"),), "must be non-empty"),
    ],
)
def test_invalid_capability_graphs_are_rejected(
    capabilities: tuple[Capability, ...],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_capabilities(capabilities)


def test_public_install_loads_modules_in_order_and_replaces_help_once() -> None:
    loaded: list[str] = []

    def final_help(topic: str = "workflow") -> dict[str, Any]:
        return {"ok": True, "topic": topic}

    guidance = SimpleNamespace(INSTRUCTIONS="final instructions", weave_help=final_help)

    def loader(name: str) -> ModuleType:
        loaded.append(name)
        if name == "weave_frontend.mcp_tested_merge_attestation_guidance":
            return guidance  # type: ignore[return-value]
        return ModuleType(name)

    capabilities = (
        Capability("base", "example.base"),
        Capability("feature", "example.feature", ("base",)),
    )
    server = _FakeFastMCP()

    manifest = install_public_capabilities(
        server,
        capabilities=capabilities,
        module_loader=loader,
    )

    assert loaded == [
        "example.base",
        "example.feature",
        "weave_frontend.mcp_tested_merge_attestation_guidance",
    ]
    assert server._mcp_server.instructions == "final instructions"
    assert server.removed == ["weave_help"]
    assert server.added == ["weave_help"]
    assert server.tools["weave_help"] is final_help
    assert "tested-merge attestations" in server.descriptions["weave_help"]
    assert manifest == capability_manifest(capabilities)


def test_public_entrypoint_exposes_the_validated_capability_manifest() -> None:
    from weave_jacquard import mcp_build as public_entrypoint

    assert capability_manifest() == public_entrypoint.PUBLIC_CAPABILITY_MANIFEST
    assert [entry["name"] for entry in public_entrypoint.PUBLIC_CAPABILITY_MANIFEST] == [
        capability.name for capability in PUBLIC_CAPABILITIES
    ]
