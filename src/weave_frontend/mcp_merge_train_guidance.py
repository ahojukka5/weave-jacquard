"""Runtime guidance for explicit order-aware merge-train previews."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Protocol

from . import mcp_selected_preflight_guidance as _base

_MERGE_TRAIN_READ_DESCRIPTION = (
    "Simulate 1–10 caller-ordered source merges against one exact catalog, exposing "
    "order-introduced conflicts, order-removed conflicts, redundancy, and virtual root "
    "transitions without compiler or publication."
)
_MERGE_TRAIN_INSTRUCTION = """
Use selected_merge_train_preview when independent source previews are insufficient
and merge order may matter. Pass 1–10 unique source branches in explicit caller
order and one unchanged catalog_id. Jacquard applies each source to an in-memory
virtual target and compares the train step with its original target preview.
The simulation can expose order_introduced_conflict, order_removed_conflict, and
later no-change redundancy. It stops at the first unresolved train conflict.
No compiler, preflight, build, or merge publication runs. Only the first clean
step can reuse the original target preview for immediate preflight. After any
real merge publication, obtain a fresh catalog and preflight before the next
source because the target head and all later publication identities have changed.
Caller order affects structural results but does not itself express priority,
quality, age, urgency, or readiness.
""".strip()

INSTRUCTIONS = f"{_base.INSTRUCTIONS}\n{_MERGE_TRAIN_INSTRUCTION}"

_MERGE_TRAIN_TOPIC: dict[str, Any] = {
    "selection": (
        "Call selected_merge_train_preview with 1–10 unique source branches in explicit "
        "caller order. Jacquard does not choose, rank, expand, or reorder the train."
    ),
    "catalog": (
        "catalog_id must describe the complete exact target/source head catalog. Jacquard "
        "checks the whole catalog before and after simulation, including unselected branches."
    ),
    "relations": [
        "consistent_clean",
        "consistent_conflict",
        "order_introduced_conflict",
        "order_removed_conflict",
    ],
    "redundancy": (
        "A later clean step can report no_changes when prior virtual merges already produced "
        "the same target state. This is structural redundancy evidence only."
    ),
    "stopping": (
        "Simulation stops at the first unresolved train conflict and reports remaining sources "
        "as not simulated because no valid later virtual target exists."
    ),
    "execution": (
        "The train is in-memory structural simulation only. It runs no compiler, build, "
        "preflight, persistent write, or merge publication."
    ),
    "publication": (
        "The first clean step returns a normal preflight call. After any real publication, "
        "refresh the complete catalog and preflight the next source against the new target head."
    ),
    "ordering": (
        "Caller order can change conflicts and redundancy, but it does not itself express "
        "priority, quality, age, urgency, or readiness."
    ),
}


def weave_help(topic: str = "workflow") -> dict[str, Any]:
    """Extend selected-preflight help with order-aware train guidance."""

    if topic == "merge_train":
        return {"ok": True, "topic": topic, "help": deepcopy(_MERGE_TRAIN_TOPIC)}

    response = _base.weave_help(topic)
    help_value = deepcopy(response["help"])
    if topic == "read":
        help_value["tools"]["selected_merge_train_preview"] = _MERGE_TRAIN_READ_DESCRIPTION
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


def install_merge_train_guidance(server: _FastMCPServer) -> None:
    """Install merge-train instructions and replace only public help."""

    server._mcp_server.instructions = INSTRUCTIONS
    server.remove_tool("weave_help")
    server.add_tool(
        weave_help,
        name="weave_help",
        description=(
            "Explain structural, revision, checkpoint, project supervision, merge queues, "
            "merge trains, selected preflight, resume, validation, and build workflows."
        ),
    )
