"""Production MCP registration for race-safe build-target mutations."""

from __future__ import annotations

from typing import Any

from . import mcp_build as _build
from .concurrent_build_targets import BuildTargetRegistry

# The registry cache contains no external resources. Replace the implementation
# and clear any test-populated instance before registering the final write tools.
_build.BuildTargetRegistry = BuildTargetRegistry
_build.build_targets.cache_clear()

mcp = _build.mcp
_result = _build._result
build_targets = _build.build_targets

for _tool_name in ("build_target_set", "build_target_delete"):
    mcp.remove_tool(_tool_name)


@mcp.tool()
def build_target_set(
    project: str,
    name: str,
    document: str,
    branch: str = "main",
    additional_documents: list[str] | None = None,
    compiler_target: str | None = None,
    expected_revision_id: str | None = None,
) -> dict[str, Any]:
    """Create or update a target with optional branch-head concurrency."""

    return _result(
        lambda: build_targets().set(
            project,
            branch,
            name,
            document,
            additional_documents=additional_documents,
            compiler_target=compiler_target,
            expected_revision_id=expected_revision_id,
        )
    )


@mcp.tool()
def build_target_delete(
    project: str,
    name: str,
    branch: str = "main",
    expected_revision_id: str | None = None,
) -> dict[str, Any]:
    """Delete one target with optional branch-head concurrency."""

    return _result(
        lambda: build_targets().delete(
            project,
            branch,
            name,
            expected_revision_id=expected_revision_id,
        )
    )
