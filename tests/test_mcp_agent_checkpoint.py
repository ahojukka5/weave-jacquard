from __future__ import annotations

from typing import Any

from weave_frontend import mcp_agent_checkpoint
from weave_frontend.resume import AgentCheckpointRegistry


class _Checkpoints:
    def __init__(self) -> None:
        self.create_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.get_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def create(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.create_calls.append((args, kwargs))
        return {
            "configured": True,
            "checkpoint_id": "checkpoint-1",
            "revision_id": "revision-2",
        }

    def get(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.get_calls.append((args, kwargs))
        return {
            "configured": True,
            "checkpoint_id": "checkpoint-1",
            "revision_id": kwargs["revision_id"],
        }


def test_checkpoint_create_forwards_structured_handoff(monkeypatch) -> None:
    checkpoints = _Checkpoints()
    monkeypatch.setattr(
        mcp_agent_checkpoint,
        "agent_checkpoints",
        lambda: checkpoints,
    )

    response = mcp_agent_checkpoint.branch_checkpoint_create(
        "demo",
        "Finish checkpoint support",
        "The checkpoint registry is implemented.",
        branch="feature",
        status="ready_for_review",
        completed=["registry", "tests"],
        next_steps=["run CI"],
        open_questions=["add labels later"],
        validation=["syntax", "ruff"],
        expected_revision_id="revision-1",
        author="checkpoint-agent",
    )

    assert response["ok"] is True
    assert response["result"]["checkpoint_id"] == "checkpoint-1"
    assert checkpoints.create_calls == [
        (
            ("demo", "feature"),
            {
                "objective": "Finish checkpoint support",
                "summary": "The checkpoint registry is implemented.",
                "status": "ready_for_review",
                "completed": ["registry", "tests"],
                "next_steps": ["run CI"],
                "open_questions": ["add labels later"],
                "validation": ["syntax", "ruff"],
                "expected_revision_id": "revision-1",
                "author": "checkpoint-agent",
            },
        )
    ]


def test_checkpoint_get_forwards_exact_revision(monkeypatch) -> None:
    checkpoints = _Checkpoints()
    monkeypatch.setattr(
        mcp_agent_checkpoint,
        "agent_checkpoints",
        lambda: checkpoints,
    )

    response = mcp_agent_checkpoint.branch_checkpoint_get(
        "demo",
        branch="reviewed",
        revision_id="revision-old",
    )

    assert response["ok"] is True
    assert response["result"]["revision_id"] == "revision-old"
    assert checkpoints.get_calls == [
        (
            ("demo", "reviewed"),
            {"revision_id": "revision-old"},
        )
    ]


def test_checkpoint_factory_uses_shared_workspace(tmp_path, monkeypatch) -> None:
    mcp_agent_checkpoint.agent_checkpoints.cache_clear()
    mcp_agent_checkpoint.workspace.cache_clear()
    monkeypatch.setenv("WEAVE_DB_PATH", str(tmp_path / "checkpoint-factory.db"))

    registry = mcp_agent_checkpoint.agent_checkpoints()
    try:
        assert isinstance(registry, AgentCheckpointRegistry)
        assert registry.workspace is mcp_agent_checkpoint.workspace()
    finally:
        registry.workspace.close()
        mcp_agent_checkpoint.agent_checkpoints.cache_clear()
        mcp_agent_checkpoint.workspace.cache_clear()
