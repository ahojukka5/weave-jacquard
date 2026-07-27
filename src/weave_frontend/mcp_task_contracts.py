"""Production MCP registration for revisioned task contracts and scoped edits."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from . import mcp_build as _build
from .mcp_server import _result, mcp, workspace
from .task_contracts import TaskContractRegistry
from .task_scoped_batch import TaskScopedBatchExecutor


@lru_cache(maxsize=1)
def task_contracts() -> TaskContractRegistry:
    """Return the shared revisioned task-contract registry."""

    return TaskContractRegistry(workspace())


@lru_cache(maxsize=1)
def task_scoped_batches() -> TaskScopedBatchExecutor:
    """Return the shared task-bound structural batch executor."""

    return TaskScopedBatchExecutor(task_contracts(), _build.edit_batches())


@mcp.tool()
def task_create(
    project: str,
    name: str,
    owner: str,
    objective: str,
    allowed_documents: list[str],
    branch: str = "main",
    dependencies: list[str] | None = None,
    required_tests: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,
    status: str = "open",
    expected_revision_id: str | None = None,
    author: str | None = None,
) -> dict[str, Any]:
    """Create one branch-bound document-scoped work contract."""

    return _result(
        lambda: task_contracts().create(
            project,
            branch,
            name,
            owner=owner,
            objective=objective,
            allowed_documents=allowed_documents,
            dependencies=dependencies,
            required_tests=required_tests,
            acceptance_criteria=acceptance_criteria,
            status=status,
            expected_revision_id=expected_revision_id,
            author=author,
        )
    )


@mcp.tool()
def task_get(
    project: str,
    name: str,
    branch: str = "main",
    revision_id: str | None = None,
) -> dict[str, Any]:
    """Read one exact revisioned task contract and its content hash."""

    return _result(
        lambda: task_contracts().get(
            project,
            name,
            branch=branch,
            revision_id=revision_id,
        )
    )


@mcp.tool()
def task_list(
    project: str,
    branch: str = "main",
    revision_id: str | None = None,
    start_after_name: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """List one stable lexical page of bounded task summaries."""

    return _result(
        lambda: task_contracts().list_page(
            project,
            branch=branch,
            revision_id=revision_id,
            start_after_name=start_after_name,
            limit=limit,
        )
    )


@mcp.tool()
def task_status_set(
    project: str,
    name: str,
    status: str,
    actor: str,
    branch: str = "main",
    expected_revision_id: str | None = None,
) -> dict[str, Any]:
    """Publish one owner-authorized task status transition."""

    return _result(
        lambda: task_contracts().set_status(
            project,
            branch,
            name,
            status,
            actor=actor,
            expected_revision_id=expected_revision_id,
        )
    )


@mcp.tool()
def task_node_apply_batch(
    project: str,
    task: str,
    document: str,
    operations: list[dict[str, Any]],
    actor: str,
    branch: str = "main",
    expected_revision_id: str | None = None,
    message: str | None = None,
    include_operation_results: bool = False,
) -> dict[str, Any]:
    """Apply one task-owned batch within its declared document scope."""

    return _result(
        lambda: task_scoped_batches().apply(
            project,
            task,
            document,
            operations,
            branch=branch,
            actor=actor,
            expected_revision_id=expected_revision_id,
            message=message,
            include_operation_results=include_operation_results,
        )
    )
