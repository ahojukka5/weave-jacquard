"""Runtime guidance for revision-pinned agent resume and handoff workflows."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Protocol

from . import mcp_guidance as _base

_RESUME_WORKFLOW_STEP = "branch_resume_snapshot first when resuming existing work"
_CHECKPOINT_WORKFLOW_STEP = "branch_checkpoint_create before handoff or stopping"
_RESUME_READ_DESCRIPTION = (
    "Compose bounded program, target, policy, context, operation, history, checkpoint, "
    "and branch orientation from one immutable revision."
)
_CHECKPOINT_READ_DESCRIPTION = (
    "Resolve the newest verified structured checkpoint on a branch head or exact "
    "first-parent revision history."
)
_CHECKPOINT_WRITE_DESCRIPTION = (
    "Publish a bounded structured objective, progress, next-step, question, and "
    "validation handoff as one immutable revision."
)
_RESUME_INSTRUCTION = """
When resuming existing work after a restart or lost context, call
branch_resume_snapshot before assembling state through separate reads. Omit
revision_id to orient from the current branch head, or pass one reviewed
project revision to recover that exact historical program, targets, policy,
context, operations, checkpoint, and first-parent history. Treat
branch_head_revision_id and the project branch list as current comparison
metadata, not as part of an explicit historical state. If agent_checkpoint is
configured, follow its objective, completed work, next steps, open questions,
and validation evidence while keeping its checkpoint_revision_id explicit.
Use the returned reproducible_fork arguments with branch_create_at_revision
when continuing from a reviewed revision, and use the exact revision-filtered
build_recovery arguments when locating stored builds.

Before transferring work to another agent or ending a work session, call
branch_checkpoint_create with expected_revision_id set to the branch state you
reviewed. Record a concise objective and summary, a truthful status, completed
work, concrete next steps, unresolved questions, and validation evidence.
Checkpoint publication does not change program state, but it advances the branch
with an immutable verified handoff revision. Use branch_checkpoint_get for a
focused historical handoff read when the complete resume snapshot is unnecessary.
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
        "Programs, source hashes, targets, merge policy, contexts, operations, the "
        "resolved agent checkpoint, and first-parent history all come from the selected "
        "revision. The current branch head and branch list are comparison metadata only."
    ),
    "checkpoint": (
        "agent_checkpoint resolves the newest verified first-parent handoff reachable "
        "from the selected revision. Its resume arguments remain pinned to "
        "checkpoint_revision_id even when later program revisions inherit that checkpoint."
    ),
    "bounds": (
        "Every collection is bounded and reports total, returned, and truncation "
        "evidence. Each build target also bounds its ordered additional-source list."
    ),
    "identity": (
        "snapshot_id hashes the complete returned evidence, including the checkpoint. "
        "Repeating the same bounded read against unchanged evidence produces the same ID."
    ),
    "continue": (
        "Use reproducible_fork with branch_create_at_revision to continue from the exact "
        "selected revision. Use build_recovery to discover verified builds filtered to "
        "that revision; build IDs are lexical content identities, not chronology."
    ),
}

_CHECKPOINT_TOPIC: dict[str, Any] = {
    "publish": (
        "Call branch_checkpoint_create before handoff or stopping. Pass the exact reviewed "
        "branch head as expected_revision_id so stale intent cannot be published."
    ),
    "fields": (
        "Provide objective, summary, status, completed, next_steps, open_questions, and "
        "validation. Keep every item concrete, truthful, non-duplicated, and bounded."
    ),
    "statuses": ["in_progress", "blocked", "ready_for_review", "complete"],
    "atomicity": (
        "The canonical checkpoint document, verified hash, operation row, revision link, "
        "immutable revision, and branch update commit or roll back together. Program state "
        "and its root hash are unchanged by checkpoint publication."
    ),
    "read": (
        "branch_checkpoint_get resolves the newest verified checkpoint on the selected "
        "revision's first-parent history. Historical reads never borrow a later checkpoint."
    ),
    "resume": (
        "A checkpoint returns branch_resume_snapshot arguments pinned to its own revision. "
        "The full resume snapshot includes the same checkpoint in agent_checkpoint."
    ),
    "errors": (
        "STALE_BRANCH_HEAD rejects stale publication. INVALID_AGENT_CHECKPOINT rejects "
        "invalid fields, formats, hashes, or stored checkpoint documents."
    ),
}


def weave_help(topic: str = "workflow") -> dict[str, Any]:
    """Extend the base structural help with resume and checkpoint guidance."""

    if topic == "resume":
        return {"ok": True, "topic": topic, "help": deepcopy(_RESUME_TOPIC)}
    if topic == "checkpoint":
        return {"ok": True, "topic": topic, "help": deepcopy(_CHECKPOINT_TOPIC)}

    response = _base.weave_help(topic)
    help_value = deepcopy(response["help"])
    if topic == "workflow":
        steps = help_value["steps"]
        if _RESUME_WORKFLOW_STEP not in steps:
            steps.insert(0, _RESUME_WORKFLOW_STEP)
        if _CHECKPOINT_WORKFLOW_STEP not in steps:
            steps.append(_CHECKPOINT_WORKFLOW_STEP)
    elif topic == "read":
        help_value["tools"]["branch_resume_snapshot"] = _RESUME_READ_DESCRIPTION
        help_value["tools"]["branch_checkpoint_get"] = _CHECKPOINT_READ_DESCRIPTION
    elif topic == "write":
        help_value["tools"]["branch_checkpoint_create"] = _CHECKPOINT_WRITE_DESCRIPTION
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
        description=(
            "Explain structural, revision, checkpoint, resume, validation, and build "
            "workflows."
        ),
    )
