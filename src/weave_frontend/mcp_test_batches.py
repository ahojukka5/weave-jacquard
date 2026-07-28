"""Production MCP registration for bounded explicit behavioral-test batches."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from .mcp_server import _result, mcp, workspace
from .mcp_test_runs import test_runs
from .mcp_test_targets import test_targets
from .quota_aware_test_batches import TestBatchService
from .runtime_container import runtime_config


@lru_cache(maxsize=1)
def test_batches() -> TestBatchService:
    """Return the shared immutable explicit test-batch service."""

    return TestBatchService(
        workspace(),
        test_targets(),
        test_runs(),
        batch_root=runtime_config().test_batch_root,
    )


@mcp.tool()
def test_batch_run(
    project: str,
    test_targets: list[str],
    branch: str = "main",
    revision_id: str | None = None,
) -> dict[str, Any]:
    """Run an explicit bounded ordered test set at one exact revision."""

    return _result(
        lambda: test_batches().run(
            project,
            test_targets,
            branch=branch,
            revision_id=revision_id,
        )
    )


@mcp.tool()
def test_batch_get(batch_id: str) -> dict[str, Any]:
    """Read and verify one immutable test-batch manifest and its run evidence."""

    return _result(lambda: test_batches().get(batch_id))
