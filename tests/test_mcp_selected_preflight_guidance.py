from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from weave_frontend import mcp_merge_impact_queue_guidance
from weave_frontend.mcp_selected_preflight_guidance import (
    INSTRUCTIONS,
    install_selected_preflight_guidance,
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


def test_selected_guidance_layers_without_mutating_impact_topics() -> None:
    base_workflow = mcp_merge_impact_queue_guidance.weave_help("workflow")
    base_read = mcp_merge_impact_queue_guidance.weave_help("read")
    base_impact = mcp_merge_impact_queue_guidance.weave_help("merge_impact_queue")

    server = _FakeFastMCP()
    install_selected_preflight_guidance(server)

    assert server._mcp_server.instructions == INSTRUCTIONS
    assert server.removed == ["weave_help"]
    assert server.tools["weave_help"] is weave_help
    assert "selected preflight" in server.descriptions["weave_help"]
    assert mcp_merge_impact_queue_guidance.weave_help("workflow") == base_workflow
    assert mcp_merge_impact_queue_guidance.weave_help("read") == base_read
    assert (
        mcp_merge_impact_queue_guidance.weave_help("merge_impact_queue")
        == base_impact
    )


def test_selected_instructions_explain_selection_catalog_and_publication() -> None:
    normalized = " ".join(INSTRUCTIONS.split())

    assert "selected_merge_preflight_batch" in normalized
    assert "1–5 unique source names" in normalized
    assert "does not select, rank, or expand" in normalized
    assert "allow_uncovered_sources" in normalized
    assert "exact target merge policy" in normalized
    assert "independently for every selected source" in normalized
    assert "selected or unselected branch-head change" in normalized
    assert "never publishes a merge" in normalized
    assert "ready_for_publication" in normalized
    assert "publication_arguments" in normalized


def test_selected_help_exposes_explicit_batch_contract() -> None:
    help_value = weave_help("selected_preflight_batch")["help"]

    assert "selected_merge_preflight_batch" in help_value["selection"]
    assert "never selects, ranks, or adds" in help_value["selection"]
    assert "catalog_id" in help_value["catalog"]
    assert "unselected branches" in help_value["catalog"]
    assert "STALE_SELECTED_PREFLIGHT_CATALOG" in help_value["catalog"]
    assert "allow_uncovered_sources" in help_value["overrides"]
    assert "exact target merge policy" in help_value["overrides"]
    assert "branch_merge_preflight" in help_value["execution"]
    assert "Per-source domain errors" in help_value["execution"]
    assert "At most five sources" in help_value["bounds"]
    assert "validation_result_limit" in help_value["bounds"]
    assert help_value["outcomes"] == [
        "ready",
        "not_ready",
        "conflict",
        "policy_error",
        "other_error",
    ]
    assert "publishes no merge" in help_value["publication"]
    assert "publication_arguments" in help_value["publication"]
    assert "does not itself express priority" in help_value["ordering"]


def test_selected_preflight_tool_is_discoverable_in_read_help() -> None:
    read_tools = weave_help("read")["help"]["tools"]

    assert "selected_merge_preflight_batch" in read_tools
    description = read_tools["selected_merge_preflight_batch"]
    assert "compiler-backed merge preflight" in description
    assert "1–5 caller-selected source branches" in description
    assert "without publishing merges" in description
