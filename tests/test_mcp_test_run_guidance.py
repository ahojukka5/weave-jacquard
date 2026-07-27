from __future__ import annotations

from weave_frontend import mcp_test_guidance
from weave_frontend.mcp_test_run_guidance import INSTRUCTIONS, weave_help


def test_run_instructions_require_probed_strict_sandbox() -> None:
    normalized = " ".join(INSTRUCTIONS.split())

    assert "sandbox_capabilities" in normalized
    assert "never falls back to an ordinary host subprocess" in normalized
    assert "successful bubblewrap isolation probe" in normalized
    assert "denied networking" in normalized
    assert "ephemeral tmpfs writes" in normalized
    assert "revision_id" in normalized
    assert "definition_hash" in normalized
    assert "sandbox policy hash" in normalized
    assert "passed=false" in normalized
    assert "SANDBOX_UNAVAILABLE" in normalized
    assert "TEST_BUILD_FAILED" in normalized


def test_run_help_exposes_security_and_evidence_boundaries() -> None:
    help_value = weave_help("test_runs")["help"]

    assert "available=false" in help_value["probe"]
    assert "revision_id" in help_value["execute"]
    assert "new user, mount, PID, network" in help_value["isolation"]
    assert "address space" in help_value["limits"]
    assert "definition_hash" in help_value["evidence"]
    assert "passed=false" in help_value["failures"]
    assert "content_base64" not in help_value["outputs"]
    assert "base64" in help_value["outputs"]
    assert "seccomp=false" in help_value["boundary"]


def test_read_and_build_help_add_run_tools_without_mutating_base_topics() -> None:
    read_tools = weave_help("read")["help"]["tools"]
    build_tools = weave_help("build")["help"]["tools"]

    assert "sandbox_capabilities" in read_tools
    assert "test_run_get" in read_tools
    assert "immutable" in read_tools["test_run_get"]
    assert "test_run_output_page" in read_tools
    assert "bounded" in read_tools["test_run_output_page"]
    assert "test_run" in build_tools
    assert "strict sandbox" in build_tools["test_run"]
    assert weave_help("test_targets") == mcp_test_guidance.weave_help("test_targets")
