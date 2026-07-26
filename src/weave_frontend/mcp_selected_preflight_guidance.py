"""Runtime guidance for explicit compiler-backed selected preflight batches."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Protocol

from . import mcp_merge_impact_queue_guidance as _base

_SELECTED_PREFLIGHT_READ_DESCRIPTION = (
    "Run compiler-backed merge preflight for 1–5 caller-selected source branches from "
    "one exact project merge catalog, returning independent bounded results without "
    "publishing merges."
)
_SELECTED_PREFLIGHT_INSTRUCTION = """
Use selected_merge_preflight_batch only after explicitly choosing source branches
from an exact project merge catalog. Pass 1–5 unique source names in the desired
caller order and the unchanged catalog_id; the tool does not select, rank, or
expand the set. Use allow_uncovered_sources only as an explicit subset and only
when the exact target merge policy permits it. Compiler-backed
branch_merge_preflight runs independently for every selected source, so ready,
failed-validation, conflict, and policy-error entries may coexist. The complete
project catalog is checked before and after compiler work; any selected or
unselected branch-head change invalidates the entire batch. The tool never
publishes a merge. A ready_for_publication result is exact guarded preflight
evidence only: invoke branch_merge with the returned publication_arguments,
which rechecks preview, preflight, policy, validation, and branch heads.
""".strip()

INSTRUCTIONS = f"{_base.INSTRUCTIONS}\n{_SELECTED_PREFLIGHT_INSTRUCTION}"

_SELECTED_PREFLIGHT_TOPIC: dict[str, Any] = {
    "selection": (
        "Call selected_merge_preflight_batch with 1–5 unique source branch names chosen "
        "explicitly by the caller. The service never selects, ranks, or adds sources."
    ),
    "catalog": (
        "catalog_id must identify the complete exact target/source head catalog. Jacquard "
        "checks the whole catalog before and after compiler work, including unselected "
        "branches, and rejects any change with STALE_SELECTED_PREFLIGHT_CATALOG."
    ),
    "overrides": (
        "allow_uncovered_sources must be an explicit subset of selected sources. Each "
        "override is still subject to the exact target merge policy."
    ),
    "execution": (
        "Normal compiler-backed branch_merge_preflight runs independently for each source "
        "in caller order. Per-source domain errors do not prevent later selected sources."
    ),
    "bounds": (
        "At most five sources are selected. validation_result_limit bounds returned target "
        "validation records and target-name lists; document_limit bounds changed and "
        "uncovered document names. Complete totals and replay calls remain available."
    ),
    "outcomes": ["ready", "not_ready", "conflict", "policy_error", "other_error"],
    "publication": (
        "The batch publishes no merge. ready_for_publication is exact preflight evidence; "
        "call branch_merge with the returned publication_arguments for guarded publication."
    ),
    "ordering": (
        "Source order is caller input and does not itself express priority, quality, age, "
        "urgency, or readiness."
    ),
}


def weave_help(topic: str = "workflow") -> dict[str, Any]:
    """Extend impact-queue help with selected compiler-backed preflight guidance."""

    if topic == "selected_preflight_batch":
        return {
            "ok": True,
            "topic": topic,
            "help": deepcopy(_SELECTED_PREFLIGHT_TOPIC),
        }

    response = _base.weave_help(topic)
    help_value = deepcopy(response["help"])
    if topic == "read":
        help_value["tools"]["selected_merge_preflight_batch"] = (
            _SELECTED_PREFLIGHT_READ_DESCRIPTION
        )
    return {**response, "help": help_value}


class _FastMCPServer(Protocol):
    _mcp_server: Any

    def remove_tool(self, name: str) -> None: ...

    def add_tool(
        self,
        function: Any,
        name: str | None = None,
        description: str | None = None,
    ) -> None: ...


def install_selected_preflight_guidance(server: _FastMCPServer) -> None:
    """Install selected-preflight instructions and replace only public help."""

    server._mcp_server.instructions = INSTRUCTIONS
    server.remove_tool("weave_help")
    server.add_tool(
        weave_help,
        name="weave_help",
        description=(
            "Explain structural, revision, checkpoint, project supervision, merge queue, "
            "merge impact, selected preflight, resume, validation, and build workflows."
        ),
    )
