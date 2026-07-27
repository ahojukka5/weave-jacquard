from __future__ import annotations

from weave_frontend import mcp_test_impact_guidance
from weave_frontend.mcp_merge_test_impact_guidance import INSTRUCTIONS, weave_help


def test_merge_impact_instructions_define_virtual_candidate_boundary() -> None:
    normalized = " ".join(INSTRUCTIONS.split())

    assert "structurally clean exact merge preview" in normalized
    assert "committed target head" in normalized
    assert "in-memory merged state" in normalized
    assert "preview_id must still match" in normalized
    assert "Conflicted previews stop" in normalized
    assert "ordinary test_batch_run is incompatible" in normalized
    assert "publishes no merge" in normalized


def test_merge_impact_help_exposes_preview_virtual_and_execution_contract() -> None:
    help_value = weave_help("merge_test_impact")["help"]

    assert "merged_root_hash" in help_value["preview"]
    assert "referenced build target" in help_value["rules"]
    assert "merge conflict" in help_value["conflicts"]
    assert "no committed revision_id" in help_value["virtual"]
    assert "candidate_execution=null" in help_value["execution"]
    assert "not priority" in help_value["pagination"]
    assert "publishes no merge" in help_value["boundary"]


def test_read_help_adds_merge_impact_tool_without_mutating_base_topics() -> None:
    read_tools = weave_help("read")["help"]["tools"]

    assert "branch_merge_test_impact" in read_tools
    assert weave_help("test_impact") == mcp_test_impact_guidance.weave_help(
        "test_impact"
    )
