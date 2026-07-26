"""Runtime guidance for project merge-impact queue review."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Protocol

from . import mcp_merge_queue_guidance as _base

_MERGE_IMPACT_QUEUE_READ_DESCRIPTION = (
    "Page exact-head structural merge, target-policy, named-target coverage, and "
    "checkpoint evidence without running compiler or build validation."
)
_MERGE_IMPACT_QUEUE_INSTRUCTION = """
Use project_merge_impact_queue_page when project_merge_queue_page is too shallow
and you need non-compiling target-policy and named-build-target coverage evidence.
Carry the same catalog_id and next_after_source continuation, and choose
checkpoint_scan_limit, conflict_limit, changed_document_limit,
affected_target_limit, and coverage_document_limit explicitly. Conflicted
sources stop before impact analysis. For clean sources, treat the exact target
revision policy as authoritative; source policy is visible but cannot weaken the
target. covered_program_changes and uncovered_program_changes describe named
target coverage only. They do not prove compiler correctness or merge readiness.
No compiler or build validation runs in this tool. Replay branch_merge_impact for
complete target pages and run branch_merge_preflight before publication.
""".strip()

INSTRUCTIONS = f"{_base.INSTRUCTIONS}\n{_MERGE_IMPACT_QUEUE_INSTRUCTION}"

_MERGE_IMPACT_QUEUE_TOPIC: dict[str, Any] = {
    "page": (
        "Use project_merge_impact_queue_page for one stable target/source catalog with "
        "structural preview, exact policy, checkpoint, and named-target coverage evidence."
    ),
    "catalog": (
        "Use catalog_id and next_after_source exactly as in project_merge_queue_page. Any "
        "source or target head change rejects the old catalog."
    ),
    "bounds": (
        "limit bounds sources; checkpoint_scan_limit, conflict_limit, "
        "changed_document_limit, affected_target_limit, and coverage_document_limit "
        "independently bound returned work and evidence."
    ),
    "classifications": [
        "conflicted",
        "covered_program_changes",
        "uncovered_program_changes",
        "target_definition_changes_only",
        "no_changes",
    ],
    "policy": (
        "target_merge_policy is resolved at the exact target catalog revision and is "
        "authoritative. Source policy is exact-revision review evidence only and cannot "
        "weaken target admission requirements."
    ),
    "coverage": (
        "Coverage reports changed program and target documents, covered and uncovered "
        "documents, and bounded affected named targets. It is not compiler validation."
    ),
    "compiler": (
        "No compiler, build, or affected-target validation runs. Run the returned impact "
        "call for complete pages and branch_merge_preflight before publication."
    ),
    "readiness": (
        "Policy and coverage evidence do not prove compiler correctness, preflight identity, "
        "publication-head stability, human approval, priority, or merge readiness."
    ),
}


def weave_help(topic: str = "workflow") -> dict[str, Any]:
    """Extend structural merge-queue help with non-compiling impact guidance."""

    if topic == "merge_impact_queue":
        return {
            "ok": True,
            "topic": topic,
            "help": deepcopy(_MERGE_IMPACT_QUEUE_TOPIC),
        }

    response = _base.weave_help(topic)
    help_value = deepcopy(response["help"])
    if topic == "read":
        help_value["tools"]["project_merge_impact_queue_page"] = (
            _MERGE_IMPACT_QUEUE_READ_DESCRIPTION
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


def install_merge_impact_queue_guidance(server: _FastMCPServer) -> None:
    """Install impact-queue-aware instructions and replace only public help."""

    server._mcp_server.instructions = INSTRUCTIONS
    server.remove_tool("weave_help")
    server.add_tool(
        weave_help,
        name="weave_help",
        description=(
            "Explain structural, revision, checkpoint, project supervision, merge queue, "
            "merge impact, resume, validation, and build workflows."
        ),
    )
