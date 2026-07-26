from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from weave_frontend import mcp_merge_queue_guidance
from weave_frontend.mcp_merge_impact_queue_guidance import (
    INSTRUCTIONS,
    install_merge_impact_queue_guidance,
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


def test_impact_guidance_layers_without_mutating_merge_queue_topics() -> None:
    base_workflow = mcp_merge_queue_guidance.weave_help("workflow")
    base_read = mcp_merge_queue_guidance.weave_help("read")
    base_queue = mcp_merge_queue_guidance.weave_help("merge_queue")

    server = _FakeFastMCP()
    install_merge_impact_queue_guidance(server)

    assert server._mcp_server.instructions == INSTRUCTIONS
    assert server.removed == ["weave_help"]
    assert server.tools["weave_help"] is weave_help
    assert "merge impact" in server.descriptions["weave_help"]
    assert mcp_merge_queue_guidance.weave_help("workflow") == base_workflow
    assert mcp_merge_queue_guidance.weave_help("read") == base_read
    assert mcp_merge_queue_guidance.weave_help("merge_queue") == base_queue


def test_impact_instructions_explain_policy_coverage_and_no_compiler() -> None:
    normalized = " ".join(INSTRUCTIONS.split())

    assert "project_merge_impact_queue_page" in normalized
    assert "catalog_id" in normalized
    assert "next_after_source" in normalized
    assert "affected_target_limit" in normalized
    assert "coverage_document_limit" in normalized
    assert "Conflicted sources stop before impact analysis" in normalized
    assert "target revision policy as authoritative" in normalized
    assert "source policy is visible but cannot weaken" in normalized
    assert "No compiler or build validation runs" in normalized
    assert "branch_merge_impact" in normalized
    assert "branch_merge_preflight" in normalized


def test_impact_help_exposes_classes_policy_coverage_and_later_gates() -> None:
    help_value = weave_help("merge_impact_queue")["help"]

    assert "project_merge_impact_queue_page" in help_value["page"]
    assert "catalog_id" in help_value["catalog"]
    assert "next_after_source" in help_value["catalog"]
    assert "checkpoint_scan_limit" in help_value["bounds"]
    assert "affected_target_limit" in help_value["bounds"]
    assert "coverage_document_limit" in help_value["bounds"]
    assert help_value["classifications"] == [
        "conflicted",
        "covered_program_changes",
        "uncovered_program_changes",
        "target_definition_changes_only",
        "no_changes",
    ]
    assert "target_merge_policy" in help_value["policy"]
    assert "cannot weaken" in help_value["policy"]
    assert "covered and uncovered" in help_value["coverage"]
    assert "not compiler validation" in help_value["coverage"]
    assert "No compiler" in help_value["compiler"]
    assert "branch_merge_preflight" in help_value["compiler"]
    assert "do not prove compiler correctness" in help_value["readiness"]


def test_impact_queue_tool_is_discoverable_in_read_help() -> None:
    read_tools = weave_help("read")["help"]["tools"]

    assert "project_merge_impact_queue_page" in read_tools
    description = read_tools["project_merge_impact_queue_page"]
    assert "target-policy" in description
    assert "named-target coverage" in description
    assert "without running compiler" in description
