from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from weave_frontend.mcp_guidance import INSTRUCTIONS, install_runtime_guidance, weave_help


@dataclass
class _LowLevelServer:
    instructions: str = "legacy"


class _FakeFastMCP:
    def __init__(self) -> None:
        self._mcp_server = _LowLevelServer()
        self.tools: dict[str, Any] = {"weave_help": object()}
        self.removed: list[str] = []

    def remove_tool(self, name: str) -> None:
        self.removed.append(name)
        del self.tools[name]

    def add_tool(
        self,
        function: Any,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        assert description
        self.tools[name or function.__name__] = function


def test_runtime_guidance_replaces_legacy_registration() -> None:
    server = _FakeFastMCP()
    install_runtime_guidance(server)
    assert server._mcp_server.instructions == INSTRUCTIONS
    assert server.removed == ["weave_help"]
    assert server.tools["weave_help"] is weave_help


def test_workflow_defaults_to_one_call_merge_preflight() -> None:
    steps = weave_help("workflow")["help"]["steps"]
    preflight = "branch_merge_preflight after independent agent work"
    review = "review impact, coverage, and complete affected-target validation"
    publication = "branch_merge with the returned publication_arguments when ready"
    discovery = "build_list_page when recovering an unknown stored build ID"
    inspection = "build_get to inspect immutable provenance and artifact paths"

    assert "single-node tools while exploring or repairing" in steps
    assert "node_apply_batch for one coherent known structure" in steps
    assert "program_validate for a coherent single document" in steps
    assert "build_target_validate before a named-target build" in steps
    assert preflight in steps
    assert review in steps
    assert publication in steps
    assert steps.index(preflight) < steps.index(review) < steps.index(publication)
    assert "branch_activity_summary when measuring the workflow" in steps
    assert "program_build or build_target_build" in steps
    assert discovery in steps
    assert inspection in steps
    assert steps.index(discovery) < steps.index(inspection)
    assert "build_diagnostics_page to read mapped errors after a failed build" in steps
    assert any("node_inspect with the failed revision_id" in step for step in steps)
    assert "revision_diff_page" in steps[-1]
    assert "current head" in steps[-1]


def test_instructions_explain_preflight_policy_and_build_recovery() -> None:
    normalized = " ".join(INSTRUCTIONS.split())
    assert "merge_policy_set" in INSTRUCTIONS
    assert "current target branch policy is authoritative" in normalized
    assert "cannot weaken admission" in normalized
    assert "branch_merge_preflight" in INSTRUCTIONS
    assert "publication_tool" in INSTRUCTIONS
    assert "publication_arguments" in INSTRUCTIONS
    assert "publication repeats every gate" in normalized
    assert "atomically rechecks both branch heads" in normalized
    assert "only when investigating an individual layer" in normalized
    assert "build_list_page" in INSTRUCTIONS
    assert "exact build ID is no longer in context" in normalized
    assert "carry catalog_id across pages" in normalized
    assert "verified project-matching summary" in normalized
    assert normalized.index("build_list_page") < normalized.index("build_get")


def test_batch_help_preserves_transaction_contract() -> None:
    help_value = weave_help("batch")["help"]
    assert "single-node tools" in help_value["when"]
    assert help_value["operations"] == [
        "create_form",
        "add_atom",
        "set_atom",
        "move_node",
        "wrap_node",
        "delete_node",
    ]
    assert "@name" in help_value["aliases"]
    assert "at most 256 operations" in help_value["safety"]
    assert "expected_revision_id" in help_value["safety"][2]
    assert "one immutable revision" in help_value["safety"][4]
    assert "rolls back" in help_value["safety"][5]


def test_history_help_preserves_pagination_metric_and_audit_contract() -> None:
    help_value = weave_help("history")["help"]
    assert "next_revision_id" in help_value["page"]
    assert "1..200" in help_value["bounds"]
    assert "reachable" in help_value["bounds"]
    assert "branch_head_revision_id" in help_value["stability"]
    assert "revision_operations_page" in help_value["audit"]
    assert "next_sequence_number" in help_value["audit"]
    assert "immutable" in help_value["audit"]
    assert "project-scoped" in help_value["audit"]
    assert "node_inspect" in help_value["inspection"]
    assert "revision_id" in help_value["inspection"]
    assert "branch_head_revision_id" in help_value["inspection"]
    assert "revision_diff_page" in help_value["diff"]
    assert "target_revision_id" in help_value["diff"]
    assert "next_index" in help_value["diff"]
    assert "immutable" in help_value["diff"]
    assert "branch_activity_summary" in help_value["summary"]
    assert "revisions avoided by grouping" in help_value["summary"]
    assert "Do not maximize batch size" in help_value["interpretation"]


def test_policy_help_preserves_target_authority_and_history_contract() -> None:
    help_value = weave_help("policy")["help"]
    assert "merge_policy_set" in help_value["set"]
    assert "immutable revision" in help_value["set"]
    assert "merge_policy_get" in help_value["get"]
    assert "first-parent" in help_value["get"]
    assert "revision_id" in help_value["get"]
    assert "target branch policy" in help_value["authority"]
    assert "source_policy_ignored=true" in help_value["authority"]
    assert "cannot weaken" in help_value["authority"]
    assert "directly on that target" in help_value["change"]
    assert "invalidates older preview and preflight" in help_value["change"]
    assert "configured=false" in help_value["compatibility"]
    assert help_value["strict_default"] == {
        "require_preflight": True,
        "require_affected_validation": True,
        "allow_uncovered_documents": False,
        "max_affected_targets": "choose a bounded project-appropriate value",
    }


def test_merge_help_preserves_policy_preflight_and_publication_contract() -> None:
    help_value = weave_help("merge")["help"]
    assert "target policy controls" in help_value["policy"]
    assert "source differences" in help_value["policy"]
    assert "branch_merge_preflight" in help_value["preflight"]
    assert "exact branch heads" in help_value["preflight"]
    assert "complete affected-target validation set" in help_value["preflight"]
    assert "never advances" in help_value["preflight"]
    assert "branch_merge_preview" in help_value["preview"]
    assert "deterministic preview_id" in help_value["preview"]
    assert "branch_merge_impact" in help_value["impact"]
    assert "only changes introduced" in help_value["impact"]
    assert "branch_merge_validate_affected" in help_value["validation"]
    assert "deterministic order" in help_value["validation"]
    assert "without starting a compiler" in help_value["validation"]
    assert "publication_tool" in help_value["publish"]
    assert "publication_arguments" in help_value["publish"]
    assert "Policy-aware preflight is recomputed" in help_value["publish"]
    assert "evidence" in help_value["publish"]
    assert "MERGE_UNCOVERED_DOCUMENTS" in help_value["failures"]
    assert "MERGE_VALIDATION_UNAVAILABLE" in help_value["failures"]
    assert "MERGE_VALIDATION_FAILED" in help_value["failures"]
    assert "STALE_MERGE_PREVIEW" in help_value["failures"]
    assert "MERGE_POLICY_PREFLIGHT_REQUIRED" in help_value["failures"]
    assert "MERGE_POLICY_AFFECTED_VALIDATION_REQUIRED" in help_value["failures"]
    assert "MERGE_POLICY_VIOLATION" in help_value["failures"]
    assert "STALE_MERGE_PREFLIGHT" in help_value["failures"]
    assert "TOO_MANY_AFFECTED_TARGETS" in help_value["failures"]
    assert "target policy permits" in help_value["compatibility"]


def test_read_and_write_help_expose_policy_and_build_tools() -> None:
    read_tools = weave_help("read")["help"]["tools"]
    write_tools = weave_help("write")["help"]["tools"]
    assert "merge_policy_get" in read_tools
    assert "first-parent" in read_tools["merge_policy_get"]
    assert "branch_merge_preflight" in read_tools
    assert "target-authoritative policy" in read_tools["branch_merge_preflight"]
    assert "exact preview identity" in read_tools["branch_merge_preflight"]
    assert "branch_merge_preview" in read_tools
    assert "branch_merge_impact" in read_tools
    assert "branch_merge_validate" in read_tools
    assert "branch_merge_validate_affected" in read_tools
    assert "aggregate" in read_tools["branch_merge_validate_affected"]
    assert "build_list_page" in read_tools
    assert "at most 200" in read_tools["build_list_page"]
    assert "build_get" in read_tools["build_list_page"]
    assert "merge_policy_set" in write_tools
    assert "directly on the branch" in write_tools["merge_policy_set"]
    assert "branch_merge" in write_tools
    assert "policy" in write_tools["branch_merge"]


def test_validation_distinguishes_stored_and_merge_candidate_paths() -> None:
    help_value = weave_help("validation")["help"]
    assert "program_validate" in help_value["single_document"]
    assert "build_target_validate" in help_value["multi_document"]
    assert "one immutable revision" in help_value["multi_document"]
    assert "branch_merge_preflight" in help_value["merge_candidate"]
    assert "every affected surviving target" in help_value["merge_candidate"]
    assert "uncommitted clean merge candidate" in help_value["merge_candidate"]


def test_target_help_preserves_source_order_and_preflight_contract() -> None:
    help_value = weave_help("targets")["help"]
    assert help_value["workflow"] == [
        "program_source_list to choose source documents",
        "build_target_set to store primary source, ordered additional sources, and target",
        "build_target_validate to validate the exact pinned target",
        "branch_merge_preflight to review impact, coverage, and all affected targets",
        "branch_merge with returned publication_arguments when preflight is ready",
        "build_target_build to compile the same target through weavec build",
        "build_get to inspect provenance, diagnostics, and artifacts",
    ]
    assert "exact in-memory merge candidate" in help_value["revision_rule"]
    assert "Source order is authoritative" in help_value["revision_rule"]
    assert "merge_policy_get" in help_value["tools"]
    assert "merge_policy_set" in help_value["tools"]
    assert "branch_merge_preflight" in help_value["tools"]
    assert "branch_merge_impact" in help_value["tools"]
    assert "branch_merge_validate" in help_value["tools"]
    assert "branch_merge_validate_affected" in help_value["tools"]


def test_build_help_preserves_discovery_and_repair_contract() -> None:
    help_value = weave_help("builds")["help"]
    assert "program_build" in help_value["explicit"]
    assert "build_target_build" in help_value["named"]
    assert "build_list_page" in help_value["discover"]
    assert "at most 200" in help_value["discover"]
    assert "without artifact paths" in help_value["discover"]
    assert "lexical order" in help_value["catalog"]
    assert "catalog_id" in help_value["catalog"]
    assert "next_after_build_id" in help_value["catalog"]
    assert "STALE_BUILD_CATALOG" in help_value["catalog"]
    assert "rejected_builds" in help_value["rejections"]
    assert "error codes" in help_value["rejections"]
    assert "build_get" in help_value["inspect"]
    assert "build_diagnostics_page" in help_value["inspect"]
    assert "1..200" in help_value["inspect"]
    assert "stdout or stderr" in help_value["inspect"]
    assert "revision_id" in help_value["repair"]
    assert "node_inspect" in help_value["repair"]
    assert "stable node_id" in help_value["repair"]
    assert "revision_diff_page" in help_value["repair"]
    assert "current branch" in help_value["repair"]
    assert "structural tool" in help_value["repair"]
    assert "new revision" in help_value["repair"]
