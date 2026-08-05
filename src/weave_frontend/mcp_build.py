"""MCP server extension for revision-pinned native program builds."""

from __future__ import annotations

from typing import Any

from .batch_edit import EditBatchExecutor
from .branch_activity import BranchActivityService
from .build_inspection import BuildInspectionService
from .build_targets import BuildTargetRegistry
from .errors import ValidationError
from .mcp_guidance import install_runtime_guidance
from .mcp_server import _result, mcp, workspace
from .merge_impact import MergeTargetImpactService
from .merge_preview import MergePreviewService
from .merge_validation import MergeValidationService
from .merge_validation_set import MergeValidationSetService
from .revision_diff import RevisionNodeDiffService
from .revision_inspection import RevisionNodeInspectionService
from .runtime import (
    CompilerBridge,
    clear_runtime_compiler_bridge,
    compiler_bridge_cache_info,
    runtime_service,
    runtime_services,
)
from .target_validation import BuildTargetValidator

install_runtime_guidance(mcp)
mcp.remove_tool("node_inspect")
mcp.remove_tool("branch_merge")


@runtime_service("edit_batches", depends_on=("workspace",))
def edit_batches() -> EditBatchExecutor:
    return EditBatchExecutor(workspace())


@runtime_service("branch_activity", depends_on=("workspace",))
def branch_activity() -> BranchActivityService:
    return BranchActivityService(workspace())


@runtime_service("revision_inspection", depends_on=("workspace",))
def revision_inspection() -> RevisionNodeInspectionService:
    return RevisionNodeInspectionService(workspace())


@runtime_service("revision_diffs", depends_on=("workspace",))
def revision_diffs() -> RevisionNodeDiffService:
    return RevisionNodeDiffService(workspace())


@runtime_service("merge_previews", depends_on=("workspace",))
def merge_previews() -> MergePreviewService:
    return MergePreviewService(workspace())


def compiler_bridge() -> CompilerBridge:
    """Return the compiler bridge owned by the immutable process runtime."""

    return runtime_services().compiler_bridge()


compiler_bridge.cache_clear = clear_runtime_compiler_bridge  # type: ignore[attr-defined]
compiler_bridge.cache_info = compiler_bridge_cache_info  # type: ignore[attr-defined]


@runtime_service("build_inspection", depends_on=("compiler_bridge",))
def build_inspection() -> BuildInspectionService:
    return BuildInspectionService(compiler_bridge())


@runtime_service("build_targets", depends_on=("workspace",))
def build_targets() -> BuildTargetRegistry:
    return BuildTargetRegistry(workspace())


@runtime_service(
    "merge_impacts",
    depends_on=("merge_previews", "build_targets"),
)
def merge_impacts() -> MergeTargetImpactService:
    return MergeTargetImpactService(merge_previews(), build_targets())


@runtime_service(
    "merge_validations",
    depends_on=("workspace", "merge_previews", "build_targets"),
)
def merge_validations() -> MergeValidationService:
    return MergeValidationService(workspace(), merge_previews(), build_targets())


@runtime_service(
    "merge_validation_sets",
    depends_on=("merge_impacts", "merge_validations"),
)
def merge_validation_sets() -> MergeValidationSetService:
    return MergeValidationSetService(merge_impacts(), merge_validations())


@runtime_service("build_target_validator", depends_on=("build_targets",))
def build_target_validator() -> BuildTargetValidator:
    return BuildTargetValidator(build_targets())


@mcp.tool()
def branch_merge_preview(
    project: str,
    target_branch: str,
    source_branch: str,
) -> dict[str, object]:
    """Preview a stable-ID merge without advancing either branch."""

    return _result(lambda: merge_previews().preview(project, target_branch, source_branch))


@mcp.tool()
def branch_merge_impact(
    project: str,
    target_branch: str,
    source_branch: str,
    preview_id: str | None = None,
    start_index: int = 0,
    limit: int = 50,
) -> dict[str, object]:
    """Read bounded named-target consequences for a prospective merge."""

    return _result(
        lambda: merge_impacts().page(
            project,
            target_branch,
            source_branch,
            preview_id=preview_id,
            start_index=start_index,
            limit=limit,
        )
    )


@mcp.tool()
def branch_merge_validate(
    project: str,
    target_branch: str,
    source_branch: str,
    build_target: str,
    preview_id: str | None = None,
) -> dict[str, object]:
    """Validate one named target from the exact prospective merge candidate."""

    return _result(
        lambda: merge_validations().validate(
            project,
            target_branch,
            source_branch,
            build_target,
            preview_id=preview_id,
        )
    )


@mcp.tool()
def branch_merge_validate_affected(
    project: str,
    target_branch: str,
    source_branch: str,
    preview_id: str | None = None,
    allow_uncovered_documents: bool = False,
) -> dict[str, object]:
    """Validate every affected target that survives in the merge candidate."""

    return _result(
        lambda: merge_validation_sets().validate(
            project,
            target_branch,
            source_branch,
            preview_id=preview_id,
            allow_uncovered_documents=allow_uncovered_documents,
        )
    )


def _publish_merge(
    project: str,
    target_branch: str,
    source_branch: str,
    *,
    preview_id: str | None,
    validation_target: str | None,
    validate_affected_targets: bool,
    allow_uncovered_documents: bool,
    author: str,
) -> dict[str, Any]:
    if validation_target is not None and validate_affected_targets:
        raise ValidationError(
            "INVALID_MERGE_VALIDATION_MODE",
            "choose validation_target or validate_affected_targets, not both",
        )
    if allow_uncovered_documents and not validate_affected_targets:
        raise ValidationError(
            "INVALID_MERGE_VALIDATION_MODE",
            "allow_uncovered_documents requires validate_affected_targets",
        )

    validation: dict[str, Any] | None = None
    validation_set: dict[str, Any] | None = None
    enforced_preview_id = preview_id
    if validation_target is not None:
        validation = merge_validations().validate(
            project,
            target_branch,
            source_branch,
            validation_target,
            preview_id=preview_id,
        )
        merge_validations().require_valid(validation)
        enforced_preview_id = str(validation["preview_id"])
    elif validate_affected_targets:
        validation_set = merge_validation_sets().validate(
            project,
            target_branch,
            source_branch,
            preview_id=preview_id,
            allow_uncovered_documents=allow_uncovered_documents,
        )
        merge_validation_sets().require_ready(validation_set)
        enforced_preview_id = str(validation_set["preview_id"])

    result = merge_previews().merge(
        project,
        target_branch,
        source_branch,
        preview_id=enforced_preview_id,
        author=author,
    )
    result.update(
        {
            "validation_target": validation_target,
            "validation_enforced": validation is not None,
            "merge_validation": validation,
            "affected_validation_enforced": validation_set is not None,
            "allow_uncovered_documents": allow_uncovered_documents,
            "merge_validation_set": validation_set,
        }
    )
    return result


@mcp.tool()
def branch_merge(
    project: str,
    target_branch: str,
    source_branch: str,
    preview_id: str | None = None,
    validation_target: str | None = None,
    validate_affected_targets: bool = False,
    allow_uncovered_documents: bool = False,
    author: str = "merge-agent",
) -> dict[str, object]:
    """Publish a reviewed merge with optional single or all-target validation."""

    return _result(
        lambda: _publish_merge(
            project,
            target_branch,
            source_branch,
            preview_id=preview_id,
            validation_target=validation_target,
            validate_affected_targets=validate_affected_targets,
            allow_uncovered_documents=allow_uncovered_documents,
            author=author,
        )
    )


@mcp.tool()
def node_inspect(
    project: str,
    branch: str,
    document: str,
    node_id: str,
    depth: int = 3,
    revision_id: str | None = None,
) -> dict[str, object]:
    """Inspect a stable node at a branch head or exact immutable revision."""

    return _result(
        lambda: revision_inspection().inspect(
            project,
            branch,
            document,
            node_id,
            depth=depth,
            revision_id=revision_id,
        )
    )


@mcp.tool()
def revision_diff_page(
    project: str,
    document: str,
    base_revision_id: str,
    branch: str = "main",
    target_revision_id: str | None = None,
    start_index: int = 0,
    limit: int = 50,
) -> dict[str, object]:
    """Read bounded stable-node changes between two immutable revisions."""

    return _result(
        lambda: revision_diffs().page(
            project,
            document,
            base_revision_id,
            branch=branch,
            target_revision_id=target_revision_id,
            start_index=start_index,
            limit=limit,
        )
    )


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
    """Delete one named target in a new revision."""

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


@mcp.tool()
def build_diagnostics_page(
    build_id: str,
    start_index: int = 0,
    limit: int = 50,
) -> dict[str, object]:
    """Read mapped retained diagnostics in bounded immutable build pages."""

    return _result(
        lambda: build_inspection().diagnostics_page(
            build_id,
            start_index=start_index,
            limit=limit,
        )
    )


def main() -> None:
    """Run the extended MCP server over stdio."""

    mcp.run()


if __name__ == "__main__":
    main()
