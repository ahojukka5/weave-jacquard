from __future__ import annotations

from weave_frontend import mcp_test_batch_guidance
from weave_frontend.mcp_test_impact_guidance import INSTRUCTIONS, weave_help


def test_impact_instructions_define_non_executing_structural_rules() -> None:
    normalized = " ".join(INSTRUCTIONS.split())

    assert "explicit base revision" in normalized
    assert "executes nothing" in normalized
    assert "definition changed" in normalized
    assert "build target changed" in normalized
    assert "source documents changed" in normalized
    assert "removed tests" in normalized
    assert "plan_id is stable across pages" in normalized
    assert "never execute a partial page" in normalized


def test_impact_help_exposes_rules_gaps_paging_and_batch_boundary() -> None:
    help_value = weave_help("test_impact")["help"]

    assert "target_revision_id" in help_value["compare"]
    assert "referenced build-target" in help_value["rules"]
    assert "no surviving test coverage" in help_value["gaps"]
    assert "not priority" in help_value["pagination"]
    assert "entire" in help_value["batch"]
    assert "runs no compiler or test" in help_value["boundary"]


def test_read_help_adds_impact_tool_without_mutating_base_topics() -> None:
    read_tools = weave_help("read")["help"]["tools"]

    assert "test_impact_plan" in read_tools
    assert weave_help("test_batches") == mcp_test_batch_guidance.weave_help("test_batches")
