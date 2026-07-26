"""MCP server extension for revision-pinned native program builds."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from .batch_edit import EditBatchExecutor
from .branch_activity import BranchActivityService
from .build_targets import BuildTargetRegistry
from .compiler_bridge import CompilerBridge
from .mcp_guidance import install_runtime_guidance
from .mcp_server import _result, mcp, workspace
from .target_validation import BuildTargetValidator

install_runtime_guidance(mcp)


@lru_cache(maxsize=1)
def edit_batches() -> EditBatchExecutor:
    return EditBatchExecutor(workspace())


@lru_cache(maxsize=1)
def branch_activity() -> BranchActivityService:
    return BranchActivityService(workspace())


@lru_cache(maxsize=1)
def compiler_bridge() -> CompilerBridge:
    return CompilerBridge(
        workspace(),
        build_root=os.environ.get("WEAVE_BUILD_ROOT"),
    )


@lru_cache(maxsize=1)
def build_targets() -> BuildTargetRegistry:
    return BuildTargetRegistry(workspace())


@lru_cache(maxsize=1)
def build_target_validator() -> BuildTargetValidator:
    return BuildTargetValidator(build_targets())


@mcp.tool()
def node_apply_batch(
    project: str,
    document: str,
    operations: list[dict[str, Any]],
    branch: str = "main",
    expected_revision_id: str | None = None,
    message: str | None = None,
    author: str = "agent",
    include_operation_results: bool = False,
) -> dict[str, object]:
    """Apply up to 256 flat structural edits as one immutable revision."""

    return _result(
        lambda: edit_batches().apply(
            project,
            branch,
            document,
            operations,
            expected_revision_id=expected_revision_id,
            message=message,
            author=author,
            include_operation_results=include_operation_results,
        )
    )


@mcp.tool()
def branch_history_page(
    project: str,
    branch: str = "main",
    start_revision_id: str | None = None,
    limit: int = 50,
) -> dict[str, object]:
    """Read one bounded first-parent history page with an explicit continuation."""

    return _result(
        lambda: branch_activity().history_page(
            project,
            branch,
            start_revision_id=start_revision_id,
            limit=limit,
        )
    )


@mcp.tool()
def branch_activity_summary(
    project: str,
    branch: str = "main",
) -> dict[str, object]:
    """Summarize revisions, operations, merges, authors, and edit grouping."""

    return _result(lambda: branch_activity().summary(project, branch))


@mcp.tool()
def revision_operations_page(
    project: str,
    revision_id: str,
    start_sequence_number: int = 0,
    limit: int = 50,
) -> dict[str, object]:
    """Read immutable operation audit rows in bounded sequence-number pages."""

    return _result(
        lambda: branch_activity().revision_operations_page(
            project,
            revision_id,
            start_sequence_number=start_sequence_number,
            limit=limit,
        )
    )


@mcp.tool()
def program_build(
    project: str,
    document: str,
    branch: str = "main",
    revision_id: str | None = None,
    target: str | None = None,
    additional_documents: list[str] | None = None,
) -> dict[str, object]:
    """Build an explicit ordered document set from one immutable revision."""

    return _result(
        lambda: compiler_bridge().build(
            project,
            document,
            additional_documents=additional_documents,
            branch=branch,
            revision_id=revision_id,
            target=target,
        )
    )


@mcp.tool()
def build_target_set(
    project: str,
    name: str,
    document: str,
    branch: str = "main",
    additional_documents: list[str] | None = None,
    compiler_target: str | None = None,
) -> dict[str, object]:
    """Create or update one revisioned named build target."""

    return _result(
        lambda: build_targets().set(
            project,
            branch,
            name,
            document,
            additional_documents=additional_documents,
            compiler_target=compiler_target,
        )
    )


@mcp.tool()
def build_target_list(
    project: str,
    branch: str = "main",
    revision_id: str | None = None,
) -> dict[str, object]:
    """List named build targets from a branch head or exact revision."""

    return _result(
        lambda: build_targets().list(
            project,
            branch=branch,
            revision_id=revision_id,
        )
    )


@mcp.tool()
def build_target_get(
    project: str,
    name: str,
    branch: str = "main",
    revision_id: str | None = None,
) -> dict[str, object]:
    """Read one named build target from a branch head or exact revision."""

    return _result(
        lambda: build_targets().get(
            project,
            name,
            branch=branch,
            revision_id=revision_id,
        )
    )


@mcp.tool()
def build_target_delete(
    project: str,
    name: str,
    branch: str = "main",
) -> dict[str, object]:
    """Delete one named target in a new immutable revision."""

    return _result(lambda: build_targets().delete(project, branch, name))


@mcp.tool()
def build_target_validate(
    project: str,
    name: str,
    branch: str = "main",
    revision_id: str | None = None,
) -> dict[str, object]:
    """Validate one target's exact revision and ordered source set."""

    return _result(
        lambda: build_target_validator().validate(
            project,
            name,
            branch=branch,
            revision_id=revision_id,
        )
    )


@mcp.tool()
def build_target_build(
    project: str,
    name: str,
    branch: str = "main",
    revision_id: str | None = None,
) -> dict[str, object]:
    """Build one revisioned named target through the public compiler bridge."""

    return _result(
        lambda: build_targets().build(
            compiler_bridge(),
            project,
            name,
            branch=branch,
            revision_id=revision_id,
        )
    )


@mcp.tool()
def program_source_list(
    project: str,
    branch: str = "main",
    revision_id: str | None = None,
) -> dict[str, object]:
    """List compiler source documents without reserved target metadata."""

    return _result(
        lambda: build_targets().program_documents(
            project,
            branch=branch,
            revision_id=revision_id,
        )
    )


@mcp.tool()
def build_get(build_id: str) -> dict[str, object]:
    """Return a stored build manifest and its artifact paths."""

    return _result(lambda: compiler_bridge().get(build_id))


def main() -> None:
    """Run the extended MCP server over stdio."""

    mcp.run()


if __name__ == "__main__":
    main()
