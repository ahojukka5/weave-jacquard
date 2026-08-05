"""Production MCP registration for virtual merge-candidate builds and test runs."""

from __future__ import annotations

from typing import Any

from .build_inspection import BuildInspectionService
from .mcp_build import build_targets, compiler_bridge, merge_previews
from .mcp_server import _result, mcp
from .mcp_test_targets import test_targets
from .merge_candidate_test_runs import DEFAULT_OUTPUT_PAGE_BYTES
from .runtime import RuntimeBubblewrapSandbox, runtime_config, runtime_service
from .verified_merge_candidate_build import MergeCandidateBuildService
from .verified_merge_candidate_test_runs import MergeCandidateTestBatchService


@runtime_service(
    "merge_candidate_builds",
    depends_on=("merge_previews", "build_targets", "compiler_bridge"),
)
def merge_candidate_builds() -> MergeCandidateBuildService:
    """Return the shared verified virtual-candidate build service."""

    return MergeCandidateBuildService(
        merge_previews(),
        build_targets(),
        compiler_bridge(),
        build_root=runtime_config().merge_build_root,
    )


@runtime_service(
    "merge_candidate_build_inspection",
    depends_on=("merge_candidate_builds",),
)
def merge_candidate_build_inspection() -> BuildInspectionService:
    """Return bounded diagnostics inspection for candidate build artifacts."""

    return BuildInspectionService(merge_candidate_builds())


@runtime_service(
    "merge_candidate_test_batches",
    depends_on=(
        "merge_previews",
        "test_targets",
        "merge_candidate_builds",
    ),
)
def merge_candidate_test_batches() -> MergeCandidateTestBatchService:
    """Return the shared strict virtual-candidate test execution service."""

    config = runtime_config()
    return MergeCandidateTestBatchService(
        merge_previews(),
        test_targets(),
        merge_candidate_builds(),
        RuntimeBubblewrapSandbox.from_config(config),
        run_root=config.merge_test_run_root,
    )


def _public_build(result: dict[str, Any]) -> dict[str, Any]:
    """Remove server-local paths and the executable compiler command."""

    return {
        key: value
        for key, value in result.items()
        if key not in {"artifact_paths", "build_directory", "command"}
    }


@mcp.tool()
def branch_merge_build_target(
    project: str,
    target_branch: str,
    source_branch: str,
    build_target: str,
    preview_id: str,
) -> dict[str, Any]:
    """Build one named target from an exact clean virtual merge candidate."""

    return _result(
        lambda: _public_build(
            merge_candidate_builds().build(
                project,
                target_branch,
                source_branch,
                build_target,
                preview_id=preview_id,
            )
        )
    )


@mcp.tool()
def merge_candidate_build_get(build_id: str) -> dict[str, Any]:
    """Read and verify one retained virtual-candidate build manifest."""

    return _result(lambda: _public_build(merge_candidate_builds().get(build_id)))


@mcp.tool()
def merge_candidate_build_diagnostics_page(
    build_id: str,
    start_index: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """Read one bounded page of verified candidate-build diagnostics."""

    return _result(
        lambda: merge_candidate_build_inspection().diagnostics_page(
            build_id,
            start_index=start_index,
            limit=limit,
        )
    )


@mcp.tool()
def branch_merge_test_batch_run(
    project: str,
    target_branch: str,
    source_branch: str,
    test_targets: list[str],
    preview_id: str,
) -> dict[str, Any]:
    """Run one explicit ordered test set on an exact virtual merge candidate."""

    return _result(
        lambda: merge_candidate_test_batches().run(
            project,
            target_branch,
            source_branch,
            test_targets,
            preview_id=preview_id,
        )
    )


@mcp.tool()
def merge_candidate_test_batch_get(qualification_id: str) -> dict[str, Any]:
    """Read and verify one immutable virtual-candidate test qualification."""

    return _result(lambda: merge_candidate_test_batches().get(qualification_id))


@mcp.tool()
def merge_candidate_test_output_page(
    qualification_id: str,
    test_target: str,
    stream: str,
    start_byte: int = 0,
    max_bytes: int = DEFAULT_OUTPUT_PAGE_BYTES,
) -> dict[str, Any]:
    """Read one verified bounded stdout or stderr page from candidate evidence."""

    return _result(
        lambda: merge_candidate_test_batches().output_page(
            qualification_id,
            test_target,
            stream,
            start_byte=start_byte,
            max_bytes=max_bytes,
        )
    )
