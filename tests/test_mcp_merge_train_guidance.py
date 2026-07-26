from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from weave_frontend import mcp_selected_preflight_guidance
from weave_frontend.mcp_merge_train_guidance import (
    INSTRUCTIONS,
    install_merge_train_guidance,
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


def test_train_guidance_layers_without_mutating_selected_topics() -> None:
    base_workflow = mcp_selected_preflight_guidance.weave_help("workflow")
    base_read = mcp_selected_preflight_guidance.weave_help("read")
    base_selected = mcp_selected_preflight_guidance.weave_help(
        "selected_preflight_batch"
    )

    server = _FakeFastMCP()
    install_merge_train_guidance(server)

    assert server._mcp_server.instructions == INSTRUCTIONS
    assert server.removed == ["weave_help"]
    assert server.tools["weave_help"] is weave_help
    assert "merge trains" in server.descriptions["weave_help"]
    assert mcp_selected_preflight_guidance.weave_help("workflow") == base_workflow
    assert mcp_selected_preflight_guidance.weave_help("read") == base_read
    assert (
        mcp_selected_preflight_guidance.weave_help("selected_preflight_batch")
        == base_selected
    )


def test_train_instructions_explain_order_effects_and_refresh_boundary() -> None:
    normalized = " ".join(INSTRUCTIONS.split())

    assert "selected_merge_train_preview" in normalized
    assert "1–10 unique source branches" in normalized
    assert "in-memory virtual target" in normalized
    assert "order_introduced_conflict" in normalized
    assert "order_removed_conflict" in normalized
    assert "later no-change redundancy" in normalized
    assert "stops at the first unresolved train conflict" in normalized
    assert "No compiler, preflight, build, or merge publication runs" in normalized
    assert "Only the first clean step" in normalized
    assert "fresh catalog and preflight" in normalized
    assert "does not itself express priority" in normalized


def test_train_help_exposes_selection_relations_stopping_and_publication() -> None:
    help_value = weave_help("merge_train")["help"]

    assert "selected_merge_train_preview" in help_value["selection"]
    assert "does not choose, rank, expand, or reorder" in help_value["selection"]
    assert "catalog_id" in help_value["catalog"]
    assert "unselected branches" in help_value["catalog"]
    assert help_value["relations"] == [
        "consistent_clean",
        "consistent_conflict",
        "order_introduced_conflict",
        "order_removed_conflict",
    ]
    assert "no_changes" in help_value["redundancy"]
    assert "first unresolved train conflict" in help_value["stopping"]
    assert "no compiler" in help_value["execution"]
    assert "first clean step" in help_value["publication"]
    assert "refresh the complete catalog" in help_value["publication"]
    assert "can change conflicts and redundancy" in help_value["ordering"]
    assert "does not itself express priority" in help_value["ordering"]


def test_train_tool_is_discoverable_in_read_help() -> None:
    read_tools = weave_help("read")["help"]["tools"]

    assert "selected_merge_train_preview" in read_tools
    description = read_tools["selected_merge_train_preview"]
    assert "1–10 caller-ordered source merges" in description
    assert "order-introduced conflicts" in description
    assert "without compiler or publication" in description
