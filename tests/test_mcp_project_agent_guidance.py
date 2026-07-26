from __future__ import annotations

from weave_frontend.mcp_resume_guidance import INSTRUCTIONS, weave_help


def test_project_agent_status_instructions_explain_catalog_bounds_and_non_inference() -> None:
    normalized = " ".join(INSTRUCTIONS.split())

    assert "project_agent_status_page" in normalized
    assert "catalog_id" in normalized
    assert "next_after_branch" in normalized
    assert "additions, removals, or head advances" in normalized
    assert "checkpoint_scan_limit" in normalized
    assert "bounded per-branch first-parent work" in normalized
    assert "do not prove inactivity" in normalized
    assert "review readiness" in normalized


def test_agent_status_help_exposes_catalog_states_evidence_and_follow_up() -> None:
    help_value = weave_help("agent_status")["help"]

    assert "project_agent_status_page" in help_value["page"]
    assert "catalog_id" in help_value["catalog"]
    assert "next_after_branch" in help_value["catalog"]
    assert "STALE_AGENT_STATUS_CATALOG" in help_value["catalog"]
    assert "checkpoint_scan_limit" in help_value["bounds"]
    assert help_value["states"] == [
        "head",
        "behind_head",
        "not_found_within_scan",
        "none_in_first_parent_history",
    ]
    assert "root-hash drift" in help_value["evidence"]
    assert "do not prove inactivity" in help_value["interpretation"]
    assert "review readiness" in help_value["interpretation"]
    assert "resume_head" in help_value["follow_up"]
    assert "merge preflight" in help_value["follow_up"]


def test_agent_status_tool_is_discoverable_in_read_help() -> None:
    read_tools = weave_help("read")["help"]["tools"]

    assert "project_agent_status_page" in read_tools
    description = read_tools["project_agent_status_page"]
    assert "exact catalog" in description
    assert "checkpoint lag" in description
    assert "revision-pinned resume calls" in description
