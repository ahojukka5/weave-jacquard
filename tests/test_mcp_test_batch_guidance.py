from __future__ import annotations

from weave_frontend import mcp_test_run_guidance
from weave_frontend.mcp_test_batch_guidance import INSTRUCTIONS, weave_help


def test_batch_instructions_preserve_explicit_selection_boundary() -> None:
    normalized = " ".join(INSTRUCTIONS.split())

    assert "explicit bounded unique test_targets list" in normalized
    assert "Caller order is preserved" in normalized
    assert "resolves every definition at one captured revision" in normalized
    assert "probes the strict sandbox before the first run" in normalized
    assert "individual run independently" in normalized
    assert "per-test domain errors make the batch incomplete" in normalized


def test_batch_help_exposes_order_revision_and_evidence_contract() -> None:
    help_value = weave_help("test_batches")["help"]

    assert "1 to 64" in help_value["selection"]
    assert "never expands tags" in help_value["selection"]
    assert "before any test starts" in help_value["revision"]
    assert "caller order" in help_value["execution"]
    assert "incomplete" in help_value["outcomes"]
    assert "SANDBOX_UNAVAILABLE" in help_value["errors"]
    assert "definition_hash" in help_value["evidence"]
    assert "not a project revision" in help_value["boundary"]


def test_read_and_build_help_add_batch_tools_without_mutating_base_topics() -> None:
    read_tools = weave_help("read")["help"]["tools"]
    build_tools = weave_help("build")["help"]["tools"]

    assert "test_batch_get" in read_tools
    assert "test_batch_run" in build_tools
    assert weave_help("test_runs") == mcp_test_run_guidance.weave_help("test_runs")
