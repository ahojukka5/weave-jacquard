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


def test_workflow_covers_batch_validation_build_and_inspection() -> None:
    result = weave_help("workflow")
    steps = result["help"]["steps"]

    assert "single-node tools while exploring or repairing" in steps
    assert "node_apply_batch for one coherent known structure" in steps
    assert "program_validate for a coherent single document" in steps
    assert "build_target_validate before a named-target build" in steps
    assert "branch_activity_summary when measuring the workflow" in steps
    assert "program_build or build_target_build" in steps
    assert "build_get to inspect immutable provenance and artifact paths" in steps
    assert "build_diagnostics_page to read mapped errors after a failed build" in steps
    assert any("node_inspect with the failed revision_id" in step for step in steps)
    assert "revision_diff_page" in steps[-1]
    assert "current head" in steps[-1]


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
    assert "immutable revisions" in help_value["diff"]
    assert "branch_activity_summary" in help_value["summary"]
    assert "revisions avoided by grouping" in help_value["summary"]
    assert "Do not maximize batch size" in help_value["interpretation"]


def test_validation_distinguishes_single_and_multi_document_paths() -> None:
    help_value = weave_help("validation")["help"]

    assert "program_validate" in help_value["single_document"]
    assert "build_target_validate" in help_value["multi_document"]
    assert "one immutable revision" in help_value["multi_document"]


def test_target_help_preserves_source_order_and_revision_contract() -> None:
    help_value = weave_help("targets")["help"]

    assert help_value["workflow"] == [
        "program_source_list to choose source documents",
        "build_target_set to store primary source, ordered additional sources, and target",
        "build_target_validate to validate the exact pinned target",
        "build_target_build to compile the same target through weavec build",
        "build_get to inspect provenance, diagnostics, and artifacts",
    ]
    assert "same branch head or explicit revision" in help_value["revision_rule"]
    assert "Source order is authoritative" in help_value["revision_rule"]


def test_build_help_preserves_bounded_diagnostic_repair_contract() -> None:
    help_value = weave_help("builds")["help"]

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
