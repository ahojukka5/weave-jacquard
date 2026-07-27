"""Production MCP registration for revision-pinned agent resume snapshots."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from .mcp_agent_checkpoint import agent_checkpoints
from .mcp_build import build_targets
from .mcp_preflight import merge_policies
from .mcp_server import _result, mcp, workspace
from .mcp_task_contracts import task_contracts
from .mcp_test_targets import test_targets
from .resume_snapshot import ResumeSnapshotService
from .task_resume_snapshot import TaskResumeSnapshotService


@lru_cache(maxsize=1)
def resume_snapshots() -> ResumeSnapshotService:
    """Return the shared bounded resume-snapshot service."""

    return TaskResumeSnapshotService(
        workspace(),
        build_targets(),
        merge_policies(),
        agent_checkpoints(),
        test_targets(),
        task_contracts(),
    )


@mcp.tool()
def branch_resume_snapshot(
    project: str,
    branch: str = "main",
    revision_id: str | None = None,
    document_limit: int = 100,
    target_limit: int = 50,
    target_source_limit: int = 50,
    test_target_limit: int = 50,
    task_limit: int = 50,
    context_limit: int = 20,
    branch_limit: int = 50,
    history_limit: int = 10,
    operation_limit: int = 50,
) -> dict[str, Any]:
    """Orient a restarted agent from one exact bounded immutable project state."""

    return _result(
        lambda: resume_snapshots().snapshot(
            project,
            branch,
            revision_id=revision_id,
            document_limit=document_limit,
            target_limit=target_limit,
            target_source_limit=target_source_limit,
            test_target_limit=test_target_limit,
            task_limit=task_limit,
            context_limit=context_limit,
            branch_limit=branch_limit,
            history_limit=history_limit,
            operation_limit=operation_limit,
        )
    )
