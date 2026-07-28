"""Production MCP registration for race-safe program and node mutations."""

from __future__ import annotations

from typing import Any

from . import mcp_build as _build
from . import mcp_server as _server
from .runtime_container import (
    clear_runtime_compiler_bridge,
    compiler_bridge_cache_info,
    reset_runtime_services,
    runtime_services,
    workspace_cache_info,
)


def workspace() -> Any:
    """Return the race-safe workspace owned by the typed process runtime."""

    return runtime_services().workspace()


def compiler_bridge() -> Any:
    """Return the quota-capable compiler bridge owned by the typed process runtime."""

    return runtime_services().compiler_bridge()


workspace.cache_clear = reset_runtime_services  # type: ignore[attr-defined]
workspace.cache_info = workspace_cache_info  # type: ignore[attr-defined]
compiler_bridge.cache_clear = clear_runtime_compiler_bridge  # type: ignore[attr-defined]
compiler_bridge.cache_info = compiler_bridge_cache_info  # type: ignore[attr-defined]


def install_capability() -> None:
    """Install runtime-backed factories before dependent capabilities are imported."""

    _server.workspace = workspace
    _build.workspace = workspace
    _build.compiler_bridge = compiler_bridge
    for factory in (
        _build.edit_batches,
        _build.branch_activity,
        _build.revision_inspection,
        _build.revision_diffs,
        _build.merge_previews,
        _build.build_inspection,
        _build.build_targets,
        _build.merge_impacts,
        _build.merge_validations,
        _build.merge_validation_sets,
        _build.build_target_validator,
    ):
        factory.cache_clear()


install_capability()

mcp = _server.mcp
_result = _server._result

for _tool_name in (
    "program_create",
    "program_import",
    "node_create_form",
    "node_add_atom",
    "node_set_atom",
    "node_delete",
    "node_move",
    "node_wrap",
):
    mcp.remove_tool(_tool_name)


@mcp.tool()
def program_create(
    project: str,
    branch: str,
    document: str,
    program_name: str,
    version: str = "0.1",
    expected_revision_id: str | None = None,
) -> dict[str, Any]:
    """Create one program with optional optimistic branch-head concurrency."""

    return _result(
        lambda: workspace().create_program(
            project,
            branch,
            document,
            program_name=program_name,
            version=version,
            expected_revision_id=expected_revision_id,
        )
    )


@mcp.tool()
def program_import(
    project: str,
    branch: str,
    document: str,
    source: str,
    replace: bool = False,
    expected_revision_id: str | None = None,
) -> dict[str, Any]:
    """Import source with optional optimistic branch-head concurrency."""

    return _result(
        lambda: workspace().import_program(
            project,
            branch,
            document,
            source,
            replace=replace,
            expected_revision_id=expected_revision_id,
        )
    )


@mcp.tool()
def node_create_form(
    project: str,
    branch: str,
    document: str,
    parent_id: str,
    head: str,
    position: int | None = None,
    expected_revision_id: str | None = None,
) -> dict[str, Any]:
    """Create one form with optional optimistic branch-head concurrency."""

    return _result(
        lambda: workspace().create_form(
            project,
            branch,
            document,
            parent_id,
            head,
            position=position,
            expected_revision_id=expected_revision_id,
        )
    )


@mcp.tool()
def node_add_atom(
    project: str,
    branch: str,
    document: str,
    parent_id: str,
    kind: str,
    value: Any,
    position: int | None = None,
    expected_revision_id: str | None = None,
) -> dict[str, Any]:
    """Attach one atom with optional optimistic branch-head concurrency."""

    return _result(
        lambda: workspace().add_atom(
            project,
            branch,
            document,
            parent_id,
            kind,
            value,
            position=position,
            expected_revision_id=expected_revision_id,
        )
    )


@mcp.tool()
def node_set_atom(
    project: str,
    branch: str,
    document: str,
    node_id: str,
    value: Any,
    expected_revision_id: str | None = None,
) -> dict[str, Any]:
    """Change one atom with optional optimistic branch-head concurrency."""

    return _result(
        lambda: workspace().set_atom(
            project,
            branch,
            document,
            node_id,
            value,
            expected_revision_id=expected_revision_id,
        )
    )


@mcp.tool()
def node_delete(
    project: str,
    branch: str,
    document: str,
    node_id: str,
    expected_revision_id: str | None = None,
) -> dict[str, Any]:
    """Delete one subtree with optional optimistic branch-head concurrency."""

    return _result(
        lambda: workspace().delete_node(
            project,
            branch,
            document,
            node_id,
            expected_revision_id=expected_revision_id,
        )
    )


@mcp.tool()
def node_move(
    project: str,
    branch: str,
    document: str,
    node_id: str,
    new_parent_id: str,
    position: int | None = None,
    expected_revision_id: str | None = None,
) -> dict[str, Any]:
    """Move one stable node with optional optimistic branch-head concurrency."""

    return _result(
        lambda: workspace().move_node(
            project,
            branch,
            document,
            node_id,
            new_parent_id,
            position=position,
            expected_revision_id=expected_revision_id,
        )
    )


@mcp.tool()
def node_wrap(
    project: str,
    branch: str,
    document: str,
    node_id: str,
    head: str,
    expected_revision_id: str | None = None,
) -> dict[str, Any]:
    """Wrap one stable node with optional optimistic branch-head concurrency."""

    return _result(
        lambda: workspace().wrap_node(
            project,
            branch,
            document,
            node_id,
            head,
            expected_revision_id=expected_revision_id,
        )
    )
