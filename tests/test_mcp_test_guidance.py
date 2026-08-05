from __future__ import annotations

from weave_frontend import mcp_merge_train_guidance
from weave_frontend.mcp_test_guidance import INSTRUCTIONS, weave_help


def test_test_instructions_define_revision_and_execution_boundary() -> None:
    normalized = " ".join(INSTRUCTIONS.split())

    assert "test_target_set" in normalized
    assert "existing named build target" in normalized
    assert "controlled stdin" in normalized
    assert "isolated filesystem policy" in normalized
    assert "denied network access" in normalized
    assert "definition_hash" in normalized
    assert "bounded lexical test_target_list summaries" in normalized
    assert "They do not execute programs" in normalized
    assert "same revision and definition hash" in normalized
    assert "not treat the existence of a test target as proof" in normalized


def test_test_help_exposes_identity_discovery_and_sandbox_contract() -> None:
    help_value = weave_help("test_targets")["help"]

    assert "test_target_set" in help_value["define"]
    assert "expected_revision_id" in help_value["define"]
    assert "expected exit code" in help_value["expectations"]
    assert "definition_hash" in help_value["identity"]
    assert "next_after_name" in help_value["discovery"]
    assert "expectation byte counts" in help_value["discovery"]
    assert "network_policy='deny'" in help_value["sandbox"]
    assert "filesystem_policy='isolated'" in help_value["sandbox"]
    assert "test_target_get" in help_value["revision"]
    assert "excluded from compiler source sets" in help_value["metadata"]
    assert "no program execution" in help_value["execution"]


def test_read_and_write_help_add_test_tools_without_mutating_base_topics() -> None:
    read_tools = weave_help("read")["help"]["tools"]
    write_tools = weave_help("write")["help"]["tools"]

    assert "test_target_get" in read_tools
    assert "full hashed" in read_tools["test_target_get"]
    assert "test_target_list" in read_tools
    assert "bounded lexical" in read_tools["test_target_list"]
    assert "test_target_set" in write_tools
    assert "hashed sandbox-ready" in write_tools["test_target_set"]
    assert "test_target_delete" in write_tools
    assert weave_help("merge_train") == mcp_merge_train_guidance.weave_help("merge_train")
