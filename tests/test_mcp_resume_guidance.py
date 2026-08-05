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
    base_write = mcp_guidance.weave_help("write")

    server = _FakeFastMCP()
    install_resume_guidance(server)

    assert server._mcp_server.instructions == INSTRUCTIONS
    assert server.removed == ["weave_help"]
    assert server.tools["weave_help"] is weave_help
    assert "checkpoint" in server.descriptions["weave_help"]
    assert "supervision" in server.descriptions["weave_help"]
    assert "resume" in server.descriptions["weave_help"]
    assert mcp_guidance.weave_help("workflow") == base_workflow
    assert mcp_guidance.weave_help("read") == base_read
    assert mcp_guidance.weave_help("write") == base_write


def test_resume_instructions_explain_orientation_handoff_and_supervision() -> None:
    normalized = " ".join(INSTRUCTIONS.split())

    assert "branch_resume_snapshot" in normalized
    assert "before assembling state through separate reads" in normalized
    assert "exact historical program, targets, policy, context" in normalized
    assert "comparison metadata" in normalized
    assert "agent_checkpoint" in normalized
    assert "branch_create_at_revision" in normalized
    assert "build_recovery" in normalized
    assert "branch_checkpoint_create" in normalized
    assert "Before transferring work" in normalized
    assert "expected_revision_id" in normalized
    assert "branch_checkpoint_get" in normalized
    assert "branch_checkpoint_history_page" in normalized
    assert "revision_scan_limit" in normalized
    assert "next_revision_id" in normalized
    assert "branch_checkpoint_compare" in normalized
    assert "does not itself prove completion" in normalized
    assert "does not imply first-parent ancestry" in normalized


def test_resume_help_exposes_restart_consistency_and_checkpoint_contract() -> None:
    help_value = weave_help("resume")["help"]

    assert "restarts" in help_value["when"]
    assert "revision_id" in help_value["revision"]
    assert "selected revision" in help_value["consistency"]
    assert "comparison metadata" in help_value["consistency"]
    assert "agent checkpoint" in help_value["consistency"]
    assert "checkpoint_revision_id" in help_value["checkpoint"]
    assert "Every collection is bounded" in help_value["bounds"]
    assert "additional-source" in help_value["bounds"]
    assert "snapshot_id" in help_value["identity"]
    assert "including the checkpoint" in help_value["identity"]
    assert "branch_create_at_revision" in help_value["continue"]
    assert "not chronology" in help_value["continue"]


def test_checkpoint_help_exposes_atomic_handoff_and_supervision() -> None:
    help_value = weave_help("checkpoint")["help"]

    assert "branch_checkpoint_create" in help_value["publish"]
    assert "expected_revision_id" in help_value["publish"]
    assert "objective" in help_value["fields"]
    assert "next_steps" in help_value["fields"]
    assert help_value["statuses"] == [
        "in_progress",
        "blocked",
        "ready_for_review",
        "complete",
    ]
    assert "commit or roll back together" in help_value["atomicity"]
    assert "root hash are unchanged" in help_value["atomicity"]
    assert "branch_checkpoint_get" in help_value["read"]
    assert "Historical reads never borrow" in help_value["read"]
    assert "branch_checkpoint_history_page" in help_value["history"]
    assert "revision_scan_limit" not in help_value["history"]
    assert "next_revision_id" in help_value["history"]
    assert "branch_checkpoint_compare" in help_value["compare"]
    assert "without semantic inference" in help_value["compare"]
    assert "branch_resume_snapshot" in help_value["resume"]
    assert "STALE_BRANCH_HEAD" in help_value["errors"]
    assert "INVALID_AGENT_CHECKPOINT" in help_value["errors"]
    assert "CHECKPOINT_REVISION_REQUIRED" in help_value["errors"]


def test_checkpoint_timeline_help_exposes_bounds_continuation_and_deltas() -> None:
    help_value = weave_help("checkpoint_timeline")["help"]

    assert "branch_checkpoint_history_page" in help_value["page"]
    assert "revision_scan_limit" in help_value["page"]
    assert "next_revision_id" in help_value["continuation"]
    assert "first unscanned revision" in help_value["continuation"]
    assert "branch_resume_snapshot" in help_value["entries"]
    assert "branch_checkpoint_compare" in help_value["compare"]
    assert "next_steps" in help_value["compare"]
    assert "does not prove completion" in help_value["interpretation"]
    assert "page_id" in help_value["identity"]
    assert "comparison_id" in help_value["identity"]


def test_workflow_read_and_write_help_add_handoff_without_changing_other_topics() -> None:
    workflow = weave_help("workflow")["help"]
    read_tools = weave_help("read")["help"]["tools"]
    write_tools = weave_help("write")["help"]["tools"]
    merge = weave_help("merge")

    assert workflow["steps"][0] == ("branch_resume_snapshot first when resuming existing work")
    assert workflow["steps"][-1] == ("branch_checkpoint_create before handoff or stopping")
    assert "branch_resume_snapshot" in read_tools
    assert "one immutable revision" in read_tools["branch_resume_snapshot"]
    assert "branch_checkpoint_get" in read_tools
    assert "first-parent" in read_tools["branch_checkpoint_get"]
    assert "branch_checkpoint_history_page" in read_tools
    assert "revision-scan" in read_tools["branch_checkpoint_history_page"]
    assert "branch_checkpoint_compare" in read_tools
    assert "without inferring" in read_tools["branch_checkpoint_compare"]
    assert "branch_checkpoint_create" in write_tools
    assert "structured objective" in write_tools["branch_checkpoint_create"]
    assert merge == mcp_guidance.weave_help("merge")
