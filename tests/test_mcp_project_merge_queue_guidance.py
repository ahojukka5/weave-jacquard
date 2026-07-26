from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from weave_frontend import mcp_resume_guidance
from weave_frontend.mcp_merge_queue_guidance import (
    INSTRUCTIONS,
    install_merge_queue_guidance,
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


def test_merge_queue_guidance_layers_without_mutating_base_topics() -> None:
    base_workflow = mcp_resume_guidance.weave_help("workflow")
    base_read = mcp_resume_guidance.weave_help("read")
    base_status = mcp_resume_guidance.weave_help("agent_status")

    server = _FakeFastMCP()
    install_merge_queue_guidance(server)

    assert server._mcp_server.instructions == INSTRUCTIONS
    assert server.removed == ["weave_help"]
    assert server.tools["weave_help"] is weave_help
    assert "merge queue" in server.descriptions["weave_help"]
    assert mcp_resume_guidance.weave_help("workflow") == base_workflow
    assert mcp_resume_guidance.weave_help("read") == base_read
    assert mcp_resume_guidance.weave_help("agent_status") == base_status


def test_merge_queue_instructions_explain_catalog_gates_and_ordering() -> None:
    normalized = " ".join(INSTRUCTIONS.split())

    assert "project_merge_queue_page" in normalized
    assert "catalog_id" in normalized
    assert "next_after_source" in normalized
    assert "checkpoint_scan_limit" in normalized
    assert "conflict_limit" in normalized
    assert "changed_document_limit" in normalized
    assert "structural preview success only" in normalized
    assert "branch_merge_preflight" in normalized
    assert "does not represent priority" in normalized
    assert "checkpoint freshness" in normalized


def test_merge_queue_help_exposes_bounds_classifications_and_follow_up() -> None:
    help_value = weave_help("merge_queue")["help"]

    assert "project_merge_queue_page" in help_value["page"]
    assert "catalog_id" in help_value["catalog"]
    assert "next_after_source" in help_value["catalog"]
    assert "STALE_PROJECT_MERGE_QUEUE_CATALOG" in help_value["catalog"]
    assert "checkpoint_scan_limit" in help_value["bounds"]
    assert "conflict_limit" in help_value["bounds"]
    assert "changed_document_limit" in help_value["bounds"]
    assert help_value["classifications"] == [
        "clean_changes",
        "clean_no_changes",
        "conflicted",
    ]
    assert "structural preview succeeded only" in help_value["readiness"]
    assert "compiler validation" in help_value["readiness"]
    assert "full_preview" in help_value["follow_up"]
    assert "preflight" in help_value["follow_up"]
    assert "does not express priority" in help_value["ordering"]


def test_merge_queue_tool_is_discoverable_in_read_help() -> None:
    read_tools = weave_help("read")["help"]["tools"]

    assert "project_merge_queue_page" in read_tools
    description = read_tools["project_merge_queue_page"]
    assert "exact-head" in description
    assert "bounded conflicts" in description
    assert "replayable full-preview or preflight calls" in description
