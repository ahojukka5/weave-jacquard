"""Runtime guidance for stable project merge-queue supervision."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Protocol

from . import mcp_resume_guidance as _base

_MERGE_QUEUE_READ_DESCRIPTION = (
    "Page compact exact-head source-to-target merge previews within one stable branch "
    "catalog, with bounded conflicts, changed documents, checkpoint evidence, and "
    "replayable full-preview or preflight calls."
)
_MERGE_QUEUE_INSTRUCTION = """
For project-wide merge supervision, use project_merge_queue_page. Select one
explicit target branch, carry catalog_id and next_after_source across pages, and
choose checkpoint_scan_limit, conflict_limit, and changed_document_limit
explicitly. A stale catalog means at least one branch was added, removed, or
advanced; refresh instead of combining pages from different branch-head sets.
Treat mergeable as structural preview success only. It does not prove merge
policy admission, build-target coverage, compiler validation, preflight identity,
or unchanged publication heads. Follow the returned branch_merge_preflight call
before publication. Lexical source order is deterministic pagination only and
does not represent priority, urgency, age, quality, checkpoint freshness, or
readiness.
""".strip()

INSTRUCTIONS = f"{_base.INSTRUCTIONS}\n{_MERGE_QUEUE_INSTRUCTION}"

_MERGE_QUEUE_TOPIC: dict[str, Any] = {
    "page": (
        "Use project_merge_queue_page to compare every paged source branch against one "
        "explicit target branch using exact current branch heads."
    ),
    "catalog": (
        "Carry catalog_id and next_after_source across pages. Branch additions, removals, "
        "or head advances reject the old catalog with STALE_PROJECT_MERGE_QUEUE_CATALOG."
    ),
    "bounds": (
        "limit bounds source entries. checkpoint_scan_limit bounds first-parent checkpoint "
        "work per source; conflict_limit and changed_document_limit bound compact evidence."
    ),
    "classifications": ["clean_changes", "clean_no_changes", "conflicted"],
    "readiness": (
        "mergeable means the stable-ID structural preview succeeded only. Policy, target "
        "coverage, compiler validation, preflight identity, and publication heads remain "
        "separate gates."
    ),
    "follow_up": (
        "Use full_preview for complete node/document change evidence. For mergeable entries, "
        "run the returned preflight call before branch_merge publication."
    ),
    "ordering": (
        "Lexical source order is deterministic pagination only. It does not express priority, "
        "urgency, age, quality, checkpoint freshness, or readiness."
    ),
}


def weave_help(topic: str = "workflow") -> dict[str, Any]:
    """Extend existing runtime help with stable merge-queue guidance."""

    if topic == "merge_queue":
        return {"ok": True, "topic": topic, "help": deepcopy(_MERGE_QUEUE_TOPIC)}

    response = _base.weave_help(topic)
    help_value = deepcopy(response["help"])
    if topic == "read":
        help_value["tools"]["project_merge_queue_page"] = _MERGE_QUEUE_READ_DESCRIPTION
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


def install_merge_queue_guidance(server: _FastMCPServer) -> None:
    """Install merge-queue-aware instructions and replace only public help."""

    server._mcp_server.instructions = INSTRUCTIONS
    server.remove_tool("weave_help")
    server.add_tool(
        weave_help,
        name="weave_help",
        description=(
            "Explain structural, revision, checkpoint, project supervision, merge queue, "
            "resume, validation, and build workflows."
        ),
    )
