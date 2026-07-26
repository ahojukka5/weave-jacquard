from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from weave_frontend import mcp_guidance
from weave_frontend.mcp_resume_guidance import (
    INSTRUCTIONS,
    install_resume_guidance,
    weave_help,
)


@dataclass
class _LowLevelServer:
    instructions: str = "legacy"


class _FakeFastMCP:
    def __init__(self) -> None:
        self._mcp_server = _LowLevelServer()
        self.tools: dict[str, Any] = {"weave_help": object()}
        self.removed: list[str] = []
        self.descriptions: dict[str, str] = {}

    def remove_tool(self, name: str) -> None:
        self.removed.append(name)
        del self.tools[name]

    def add_tool(
        self,
        function: Any,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        tool_name = name or function.__name__
        assert description
        self.tools[tool_name] = function
        self.descriptions[tool_name] = description


def test_resume_guidance_replaces_help_without_mutating_base_topics() -> None:
    base_workflow = mcp_guidance.weave_help("workflow")
    base_read = mcp_guidance.weave_help("read")

    server = _FakeFastMCP()
    install_resume_guidance(server)

    assert server._mcp_server.instructions == INSTRUCTIONS
    assert server.removed == ["weave_help"]
    assert server.tools["weave_help"] is weave_help
    assert "resume" in server.descriptions["weave_help"]
    assert mcp_guidance.weave_help("workflow") == base_workflow
    assert mcp_guidance.weave_help("read") == base_read


def test_resume_instructions_explain_exact_revision_orientation() -> None:
    normalized = " ".join(INSTRUCTIONS.split())

    assert "branch_resume_snapshot" in normalized
    assert "before assembling state through separate reads" in normalized
    assert "exact historical program, targets, policy, context" in normalized
    assert "comparison metadata" in normalized
    assert "branch_create_at_revision" in normalized
    assert "build_recovery" in normalized


def test_resume_help_exposes_restart_consistency_and_follow_up_contract() -> None:
    help_value = weave_help("resume")["help"]

    assert "restarts" in help_value["when"]
    assert "revision_id" in help_value["revision"]
    assert "selected revision" in help_value["consistency"]
    assert "comparison metadata" in help_value["consistency"]
    assert "Every collection is bounded" in help_value["bounds"]
    assert "additional-source" in help_value["bounds"]
    assert "snapshot_id" in help_value["identity"]
    assert "branch_create_at_revision" in help_value["continue"]
    assert "not chronology" in help_value["continue"]


def test_workflow_and_read_help_add_resume_without_changing_other_topics() -> None:
    workflow = weave_help("workflow")["help"]
    read_tools = weave_help("read")["help"]["tools"]
    merge = weave_help("merge")

    assert workflow["steps"][0] == (
        "branch_resume_snapshot first when resuming existing work"
    )
    assert "branch_resume_snapshot" in read_tools
    assert "one immutable revision" in read_tools["branch_resume_snapshot"]
    assert merge == mcp_guidance.weave_help("merge")
