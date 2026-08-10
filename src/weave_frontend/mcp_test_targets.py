"""Production MCP registration for revisioned behavioral test definitions."""

from __future__ import annotations

from typing import Any

from . import mcp_build as _build
from . import selected_merge_train_preview as _train
from .builds import MetadataBuildTargetRegistry as BuildTargetRegistry
from .mcp_server import _result, mcp, workspace
from .metadata_merge_impact import MergeTargetImpactService
from .metadata_merge_preview import MergePreviewService
from .metadata_selected_merge_train_preview import SelectedMergeTrainPreviewService
from .runtime import runtime_service
from .test_target_views import (
    DEFAULT_TEST_TARGET_PAGE_SIZE,
    TestTargetPageService,
    VerifiedTestTargetRegistry,
)
from .test_targets import (
    DEFAULT_FILE_BYTES,
    DEFAULT_MEMORY_BYTES,
    DEFAULT_OUTPUT_BYTES,
    DEFAULT_TIMEOUT_MS,
)


def install_metadata_aware_merge_services() -> None:
    """Install the final metadata-aware service classes and clear stale compositions."""

    _build.BuildTargetRegistry = BuildTargetRegistry
    _build.MergePreviewService = MergePreviewService
    _build.MergeTargetImpactService = MergeTargetImpactService
    _train.SelectedMergeTrainPreviewService = SelectedMergeTrainPreviewService
    for service in (
        _build.build_targets,
        _build.merge_previews,
        _build.merge_impacts,
        _build.merge_validations,
        _build.merge_validation_sets,
        _build.build_target_validator,
    ):
        service.cache_clear()


@runtime_service("test_targets", depends_on=("workspace",))
def test_targets() -> VerifiedTestTargetRegistry:
    """Return the shared verified revisioned test-target registry."""

    return VerifiedTestTargetRegistry(workspace())


@runtime_service("test_target_pages", depends_on=("test_targets",))
def test_target_pages() -> TestTargetPageService:
    """Return the shared bounded test-target summary service."""

    return TestTargetPageService(test_targets())


@mcp.tool()
def test_target_set(
    project: str,
    name: str,
    build_target: str,
    branch: str = "main",
    arguments: list[str] | None = None,
    stdin: str = "",
    expected_exit_code: int = 0,
    expected_stdout: str = "",
    expected_stderr: str = "",
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    max_memory_bytes: int = DEFAULT_MEMORY_BYTES,
    max_output_bytes: int = DEFAULT_OUTPUT_BYTES,
    max_file_bytes: int = DEFAULT_FILE_BYTES,
    tags: list[str] | None = None,
    expected_revision_id: str | None = None,
    author: str = "test-agent",
) -> dict[str, Any]:
    """Create or update one hashed sandbox-ready behavioral test definition."""

    return _result(
        lambda: test_targets().set(
            project,
            branch,
            name,
            build_target,
            arguments=arguments,
            stdin=stdin,
            expected_exit_code=expected_exit_code,
            expected_stdout=expected_stdout,
            expected_stderr=expected_stderr,
            timeout_ms=timeout_ms,
            max_memory_bytes=max_memory_bytes,
            max_output_bytes=max_output_bytes,
            max_file_bytes=max_file_bytes,
            tags=tags,
            expected_revision_id=expected_revision_id,
            author=author,
        )
    )


@mcp.tool()
def test_target_get(
    project: str,
    name: str,
    branch: str = "main",
    revision_id: str | None = None,
) -> dict[str, Any]:
    """Read one full hashed test definition from a branch head or exact revision."""

    return _result(
        lambda: test_targets().get(
            project,
            name,
            branch=branch,
            revision_id=revision_id,
        )
    )


@mcp.tool()
def test_target_list(
    project: str,
    branch: str = "main",
    revision_id: str | None = None,
    start_after_name: str | None = None,
    limit: int = DEFAULT_TEST_TARGET_PAGE_SIZE,
) -> dict[str, Any]:
    """List bounded lexical test summaries from a branch head or exact revision."""

    return _result(
        lambda: test_target_pages().page(
            project,
            branch=branch,
            revision_id=revision_id,
            start_after_name=start_after_name,
            limit=limit,
        )
    )


@mcp.tool()
def test_target_delete(
    project: str,
    name: str,
    branch: str = "main",
    expected_revision_id: str | None = None,
    author: str = "test-agent",
) -> dict[str, Any]:
    """Delete one test definition in a race-safe immutable revision."""

    return _result(
        lambda: test_targets().delete(
            project,
            branch,
            name,
            expected_revision_id=expected_revision_id,
            author=author,
        )
    )
