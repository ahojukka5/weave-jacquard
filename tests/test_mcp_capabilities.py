from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from weave_frontend.mcp_capabilities import (
    PUBLIC_CAPABILITIES,
    ApplicationContext,
    Capability,
    capability_manifest,
    install_public_capabilities,
    validate_capabilities,
)
from weave_frontend.runtime import RuntimeConfig, RuntimeServices


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


def _runtime() -> RuntimeServices:
    return RuntimeServices(RuntimeConfig.from_environ({"WEAVE_DB_PATH": "capability-test.db"}))


def test_public_capabilities_have_unique_dependency_order() -> None:
    assert validate_capabilities(PUBLIC_CAPABILITIES) == PUBLIC_CAPABILITIES
    names = [capability.name for capability in PUBLIC_CAPABILITIES]

    assert names[0] == "concurrent_nodes"
    assert names[-1] == "runtime_identity"
    assert len(names) == len(set(names))
    for capability in (
        "test_targets",
        "test_runs",
        "test_batches",
        "test_impact",
        "merge_test_impact",
        "merge_candidate_test_execution",
        "tested_merge_attestations",
        "revision_evidence",
        "task_contracts",
        "revert",
        "resume_snapshot",
        "selected_merge_train_preview",
        "database_backup",
        "artifact_storage",
        "runtime_identity",
    ):
        assert capability in names
    assert names.index("concurrent_targets") < names.index("test_targets")
    assert names.index("test_targets") < names.index("test_runs")
    assert names.index("test_runs") < names.index("test_batches")
    assert names.index("test_batches") < names.index("test_impact")
    assert names.index("test_impact") < names.index("merge_test_impact")
    assert names.index("merge_test_impact") < names.index("merge_candidate_test_execution")
    assert names.index("merge_candidate_test_execution") < names.index("tested_merge_attestations")
    assert names.index("tested_merge_attestations") < names.index("revision_evidence")
    assert names.index("build_discovery") < names.index("revision_evidence")
    assert names.index("test_batches") < names.index("revision_evidence")
    assert names.index("test_targets") < names.index("task_contracts")
    assert names.index("task_contracts") < names.index("revert")
    assert names.index("tested_merge_attestations") < names.index("policy")
    assert names.index("task_contracts") < names.index("policy")
    assert names.index("build_discovery") < names.index("artifact_storage")
    assert names.index("test_batches") < names.index("artifact_storage")
    assert names.index("tested_merge_attestations") < names.index("artifact_storage")
    assert names.index("concurrent_nodes") < names.index("database_backup")
    assert names.index("revision_reads") < names.index("runtime_identity")
    assert names.index("database_backup") < names.index("runtime_identity")
    assert names.index("artifact_storage") < names.index("runtime_identity")


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


def test_public_install_uses_exact_context_and_replaces_help_once() -> None:
    loaded: list[str] = []
    installed: list[tuple[str, ApplicationContext | None]] = []

    def final_help(topic: str = "workflow") -> dict[str, Any]:
        return {"ok": True, "topic": topic}

    guidance = SimpleNamespace(INSTRUCTIONS="final instructions", weave_help=final_help)

    def loader(name: str) -> ModuleType:
        loaded.append(name)
        if name == "weave_frontend.mcp_revert_guidance":
            return guidance  # type: ignore[return-value]
        module = ModuleType(name)
        if name == "example.base":
            module.install_capability = (  # type: ignore[attr-defined]
                lambda context: installed.append(("base", context))
            )
        if name == "example.feature":
            module.install_capability = (  # type: ignore[attr-defined]
                lambda context: installed.append(("feature", context))
            )
        return module

    capabilities = (
        Capability("base", "example.base"),
        Capability("feature", "example.feature", ("base",)),
    )
    server = _FakeFastMCP()
    runtime = _runtime()
    context = ApplicationContext(server=server, runtime=runtime)

    manifest = install_public_capabilities(
        context,
        capabilities=capabilities,
        module_loader=loader,
    )

    assert loaded == [
        "example.base",
        "example.feature",
        "weave_frontend.mcp_revert_guidance",
    ]
    assert installed == [("base", context), ("feature", context)]
    assert context.server is server
    assert context.runtime is runtime
    assert server._mcp_server.instructions == "final instructions"
    assert server.removed == ["weave_help"]
    assert server.added == ["weave_help"]
    assert server.tools["weave_help"] is final_help
    assert "immutable reverts" in server.descriptions["weave_help"]
    assert manifest == capability_manifest(capabilities)


def test_public_install_rejects_zero_argument_installer() -> None:
    server = _FakeFastMCP()
    context = ApplicationContext(server=server, runtime=_runtime())

    def loader(name: str) -> ModuleType:
        if name == "weave_frontend.mcp_revert_guidance":
            return SimpleNamespace(  # type: ignore[return-value]
                INSTRUCTIONS="unused",
                weave_help=lambda: None,
            )
        module = ModuleType(name)

        def install_capability() -> None:
            raise AssertionError("zero-argument installer must not run")

        module.install_capability = install_capability  # type: ignore[attr-defined]
        return module

    with pytest.raises(TypeError, match="exactly one ApplicationContext"):
        install_public_capabilities(
            context,
            capabilities=(Capability("invalid", "example.invalid"),),
            module_loader=loader,
        )

    assert server.removed == []
    assert server.added == []


def test_public_install_rejects_ambiguous_installer_signature() -> None:
    server = _FakeFastMCP()
    context = ApplicationContext(server=server, runtime=_runtime())

    def loader(name: str) -> ModuleType:
        if name == "weave_frontend.mcp_revert_guidance":
            return SimpleNamespace(  # type: ignore[return-value]
                INSTRUCTIONS="unused",
                weave_help=lambda: None,
            )
        module = ModuleType(name)

        def install_capability(left: object, right: object) -> None:
            raise AssertionError((left, right))

        module.install_capability = install_capability  # type: ignore[attr-defined]
        return module

    with pytest.raises(TypeError, match="exactly one ApplicationContext"):
        install_public_capabilities(
            context,
            capabilities=(Capability("invalid", "example.invalid"),),
            module_loader=loader,
        )

    assert server.removed == []
    assert server.added == []


def test_public_entrypoint_exposes_the_validated_capability_manifest() -> None:
    from weave_jacquard import mcp_build as public_entrypoint

    assert capability_manifest() == public_entrypoint.PUBLIC_CAPABILITY_MANIFEST
    assert [entry["name"] for entry in public_entrypoint.PUBLIC_CAPABILITY_MANIFEST] == [
        capability.name for capability in PUBLIC_CAPABILITIES
    ]
