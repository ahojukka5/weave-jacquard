"""Production MCP registration for revisioned agent checkpoints."""

from __future__ import annotations

from typing import Any

from .agent_checkpoint import AgentCheckpointRegistry
from .mcp_server import _result, mcp, workspace
from .runtime import runtime_service


@runtime_service("agent_checkpoints", depends_on=("workspace",))
def agent_checkpoints() -> AgentCheckpointRegistry:
    """Return the shared revisioned checkpoint registry."""

    return AgentCheckpointRegistry(workspace())


@mcp.tool()
def branch_checkpoint_create(
    project: str,
    objective: str,
    summary: str,
    branch: str = "main",
    status: str = "in_progress",
    completed: list[str] | None = None,
    next_steps: list[str] | None = None,
    open_questions: list[str] | None = None,
    validation: list[str] | None = None,
    expected_revision_id: str | None = None,
    author: str = "agent",
) -> dict[str, Any]:
    """Publish one structured handoff checkpoint as an immutable revision."""

    return _result(
        lambda: agent_checkpoints().create(
            project,
            branch,
            objective=objective,
            summary=summary,
            status=status,
            completed=completed,
            next_steps=next_steps,
            open_questions=open_questions,
            validation=validation,
            expected_revision_id=expected_revision_id,
            author=author,
        )
    )


@mcp.tool()
def branch_checkpoint_get(
    project: str,
    branch: str = "main",
    revision_id: str | None = None,
) -> dict[str, Any]:
    """Resolve the newest first-parent checkpoint at a branch head or revision."""

    return _result(
        lambda: agent_checkpoints().get(
            project,
            branch,
            revision_id=revision_id,
        )
    )
