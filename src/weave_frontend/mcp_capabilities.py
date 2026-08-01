"""Declarative assembly for the public Jacquard MCP capability set."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from importlib import import_module
from inspect import Parameter, signature
from types import ModuleType
from typing import Any, Protocol

from .application_runtime_binding import bind_application_runtime
from .runtime_container import RuntimeClosedError, RuntimeServices


@dataclass(frozen=True)
class Capability:
    """One production MCP capability module and its explicit dependencies."""

    name: str
    module: str
    depends_on: tuple[str, ...] = ()


PUBLIC_CAPABILITIES: tuple[Capability, ...] = (
    Capability("concurrent_nodes", "weave_frontend.mcp_concurrent_nodes"),
    Capability(
        "agent_checkpoint",
        "weave_frontend.mcp_agent_checkpoint",
        ("concurrent_nodes",),
    ),
    Capability(
        "agent_checkpoint_timeline",
        "weave_frontend.mcp_agent_checkpoint_timeline",
        ("agent_checkpoint",),
    ),
    Capability(
        "build_discovery",
        "weave_frontend.mcp_build_discovery",
        ("concurrent_nodes",),
    ),
    Capability(
        "concurrent_branches",
        "weave_frontend.mcp_concurrent_branches",
        ("concurrent_nodes",),
    ),
    Capability(
        "concurrent_context",
        "weave_frontend.mcp_concurrent_context",
        ("concurrent_nodes",),
    ),
    Capability(
        "concurrent_targets",
        "weave_frontend.mcp_concurrent_targets",
        ("concurrent_nodes",),
    ),
    Capability(
        "test_targets",
        "weave_frontend.mcp_test_targets",
        ("concurrent_targets",),
    ),
    Capability(
        "test_runs",
        "weave_frontend.mcp_test_runs",
        ("test_targets",),
    ),
    Capability(
        "test_batches",
        "weave_frontend.mcp_test_batches",
        ("test_runs",),
    ),
    Capability(
        "test_impact",
        "weave_frontend.mcp_test_impact",
        ("test_batches",),
    ),
    Capability(
        "merge_test_impact",
        "weave_frontend.mcp_merge_test_impact",
        ("test_impact",),
    ),
    Capability(
        "merge_candidate_test_execution",
        "weave_frontend.mcp_merge_candidate_test_runs",
        ("merge_test_impact",),
    ),
    Capability(
        "tested_merge_attestations",
        "weave_frontend.mcp_tested_merge_attestations",
        ("merge_candidate_test_execution",),
    ),
    Capability(
        "revision_evidence",
        "weave_frontend.mcp_revision_evidence",
        ("build_discovery", "test_batches", "tested_merge_attestations"),
    ),
    Capability(
        "task_contracts",
        "weave_frontend.mcp_task_contracts",
        ("test_targets",),
    ),
    Capability(
        "revert",
        "weave_frontend.mcp_revert",
        ("task_contracts",),
    ),
    Capability(
        "policy",
        "weave_frontend.mcp_policy",
        ("tested_merge_attestations", "task_contracts"),
    ),
    Capability(
        "preflight",
        "weave_frontend.mcp_preflight",
        ("policy",),
    ),
    Capability(
        "project_agent_status",
        "weave_frontend.mcp_project_agent_status",
        ("agent_checkpoint_timeline",),
    ),
    Capability(
        "project_merge_queue",
        "weave_frontend.mcp_project_merge_queue",
        ("project_agent_status", "preflight"),
    ),
    Capability(
        "project_merge_impact_queue",
        "weave_frontend.mcp_project_merge_impact_queue",
        ("project_merge_queue",),
    ),
    Capability(
        "selected_merge_preflight_batch",
        "weave_frontend.mcp_selected_merge_preflight_batch",
        ("project_merge_impact_queue",),
    ),
    Capability(
        "selected_merge_train_preview",
        "weave_frontend.mcp_selected_merge_train_preview",
        ("selected_merge_preflight_batch",),
    ),
    Capability(
        "resume_snapshot",
        "weave_frontend.mcp_resume_snapshot",
        ("agent_checkpoint", "test_targets", "task_contracts", "preflight"),
    ),
    Capability(
        "revision_reads",
        "weave_frontend.mcp_revision_reads",
        ("concurrent_nodes",),
    ),
    Capability(
        "database_backup",
        "weave_frontend.mcp_database_backup",
        ("concurrent_nodes",),
    ),
    Capability(
        "artifact_storage",
        "weave_frontend.mcp_artifact_storage",
        (
            "build_discovery",
            "test_batches",
            "tested_merge_attestations",
            "database_backup",
        ),
    ),
    Capability(
        "runtime_identity",
        "weave_frontend.mcp_runtime_identity",
        ("revision_reads", "database_backup", "artifact_storage"),
    ),
)


class _FastMCPServer(Protocol):
    _mcp_server: Any

    def remove_tool(self, name: str) -> None: ...

    def add_tool(
        self,
        function: Any,
        name: str | None = None,
        description: str | None = None,
    ) -> None: ...


@dataclass(frozen=True)
class ApplicationContext:
    """Exact server and runtime selected for one application composition."""

    server: _FastMCPServer
    runtime: RuntimeServices

    def __post_init__(self) -> None:
        if not isinstance(self.runtime, RuntimeServices):
            raise TypeError("application runtime must be a RuntimeServices instance")
        if self.runtime.closed:
            raise RuntimeClosedError("cannot compose an application with a closed runtime")


ModuleLoader = Callable[[str], ModuleType]


def validate_capabilities(capabilities: Iterable[Capability]) -> tuple[Capability, ...]:
    """Validate unique names and dependency-before-dependent ordering."""

    ordered = tuple(capabilities)
    seen: set[str] = set()
    for capability in ordered:
        if not capability.name or not capability.module:
            raise ValueError("capability names and modules must be non-empty")
        if capability.name in seen:
            raise ValueError(f"duplicate capability {capability.name!r}")
        missing = [name for name in capability.depends_on if name not in seen]
        if missing:
            raise ValueError(
                f"capability {capability.name!r} requires earlier dependencies {missing!r}"
            )
        seen.add(capability.name)
    return ordered


def capability_manifest(
    capabilities: Iterable[Capability] = PUBLIC_CAPABILITIES,
) -> tuple[dict[str, Any], ...]:
    """Return immutable JSON-ready metadata for the declared capability graph."""

    return tuple(
        {
            "name": capability.name,
            "module": capability.module,
            "depends_on": list(capability.depends_on),
        }
        for capability in validate_capabilities(capabilities)
    )


def _invoke_installer(
    installer: Callable[..., Any],
    context: ApplicationContext,
) -> None:
    """Call one supported legacy or context-aware capability installer."""

    parameters = tuple(signature(installer).parameters.values())
    if not parameters:
        installer()
        return
    if len(parameters) != 1:
        raise TypeError(
            "install_capability must accept either no arguments or one "
            "ApplicationContext"
        )

    parameter = parameters[0]
    if parameter.kind in (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD):
        installer(context)
        return
    if parameter.kind is Parameter.KEYWORD_ONLY:
        installer(**{parameter.name: context})
        return
    raise TypeError(
        "install_capability must accept either no arguments or one "
        "ApplicationContext"
    )


def install_public_capabilities(
    context: ApplicationContext,
    *,
    capabilities: Iterable[Capability] = PUBLIC_CAPABILITIES,
    module_loader: ModuleLoader = import_module,
) -> tuple[dict[str, Any], ...]:
    """Load capabilities into one exact application context in dependency order."""

    if not isinstance(context, ApplicationContext):
        raise TypeError("context must be an ApplicationContext instance")

    with bind_application_runtime(context.runtime):
        ordered = validate_capabilities(capabilities)
        for capability in ordered:
            module = module_loader(capability.module)
            installer = getattr(module, "install_capability", None)
            if callable(installer):
                _invoke_installer(installer, context)

        guidance = module_loader("weave_frontend.mcp_revert_guidance")
        server = context.server
        server._mcp_server.instructions = guidance.INSTRUCTIONS
        server.remove_tool("weave_help")
        server.add_tool(
            guidance.weave_help,
            name="weave_help",
            description=(
                "Explain structural, revision, checkpoint, project supervision, "
                "merge queues, merge trains, test definitions, strict test runs, "
                "explicit test batches, test impact plans, virtual candidate "
                "qualification, tested-merge attestations, revision evidence graphs, "
                "revisioned task contracts, scoped edits, immutable reverts, selected "
                "preflight, resume, validation, build, verified database backup, "
                "artifact storage, and runtime identity workflows."
            ),
        )
        return capability_manifest(ordered)


__all__ = [
    "ApplicationContext",
    "Capability",
    "ModuleLoader",
    "PUBLIC_CAPABILITIES",
    "capability_manifest",
    "install_public_capabilities",
    "validate_capabilities",
]
