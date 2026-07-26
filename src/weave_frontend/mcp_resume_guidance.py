"""Runtime guidance for revision-pinned agent resume snapshots."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Protocol

from . import mcp_guidance as _base

_RESUME_WORKFLOW_STEP = "branch_resume_snapshot first when resuming existing work"
_RESUME_READ_DESCRIPTION = (
    "Compose bounded program, target, policy, context, operation, history, and "
    "branch orientation from one immutable revision."
)
_RESUME_INSTRUCTION = """
When resuming existing work after a restart or lost context, call
branch_resume_snapshot before assembling state through separate reads. Omit
revision_id to orient from the current branch head, or pass one reviewed
project revision to recover that exact historical program, targets, policy,
context, operations, and first-parent history. Treat branch_head_revision_id
and the project branch list as current comparison metadata, not as part of an
explicit historical state. Use the returned reproducible_fork arguments with
branch_create_at_revision when continuing from a reviewed revision, and use
the exact revision-filtered build_recovery arguments when locating stored
builds.
""".strip()

INSTRUCTIONS = f"{_base.INSTRUCTIONS}\n{_RESUME_INSTRUCTION}"

_RESUME_TOPIC: dict[str, Any] = {
    "when": (
        "Call branch_resume_snapshot when an agent restarts, loses working memory, "
        "or receives a project and branch without a trusted current revision."
    ),
    "revision": (
        "Omit revision_id for the current branch head. Pass a project-owned immutable "
        "revision_id to recover one exact reviewed historical state."
    ),
    "consistency": (
        "Programs, source hashes, targets, merge policy, contexts, operations, and "
        "first-parent history all come from the selected revision. The current branch "
        "head and branch list are explicit comparison metadata only."
    ),
    "bounds": (
        "Every collection is bounded and reports total, returned, and truncation "
        "evidence. Each build target also bounds its ordered additional-source list."
    ),
    "identity": (
        "snapshot_id hashes the complete returned evidence. Repeating the same bounded "
        "read against unchanged evidence produces the same identity."
    ),
    "continue": (
        "Use reproducible_fork with branch_create_at_revision to continue from the exact "
        "selected revision. Use build_recovery to discover verified builds filtered to "
        "that revision; build IDs are lexical content identities, not chronology."
    ),
}


def weave_help(topic: str = "workflow") -> dict[str, Any]:
    """Extend the base structural help with resume-snapshot guidance."""

    if topic == "resume":
        return {"ok": True, "topic": topic, "help": deepcopy(_RESUME_TOPIC)}

    response = _base.weave_help(topic)
    help_value = deepcopy(response["help"])
    if topic == "workflow":
        steps = help_value["steps"]
        if _RESUME_WORKFLOW_STEP not in steps:
            steps.insert(0, _RESUME_WORKFLOW_STEP)
    elif topic == "read":
        help_value["tools"]["branch_resume_snapshot"] = _RESUME_READ_DESCRIPTION
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


def install_resume_guidance(server: _FastMCPServer) -> None:
    """Install resume-aware instructions and replace only the public help tool."""

    server._mcp_server.instructions = INSTRUCTIONS
    server.remove_tool("weave_help")
    server.add_tool(
        weave_help,
        name="weave_help",
        description="Explain structural, revision, resume, validation, and build workflows.",
    )
