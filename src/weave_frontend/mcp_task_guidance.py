"""Runtime guidance for revisioned task contracts and scoped structural edits."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from . import mcp_tested_merge_attestation_guidance as _base

_TASK_INSTRUCTION = """
Use task_create to bind autonomous work to one exact base revision, owner, branch,
document scope, dependencies, required tests, and acceptance criteria. Use
task_node_apply_batch for prepared structural work that must be enforced against
that contract; every published operation retains task identity. Task contracts do
not make ordinary node tools globally forbidden, and document scope does not claim
symbol-level semantic isolation. Use task_status_set for owner-authorized lifecycle
transitions and task_get or task_list for revision-consistent orientation.
""".strip()

INSTRUCTIONS = f"{_base.INSTRUCTIONS}\n{_TASK_INSTRUCTION}"

_TOPIC: dict[str, Any] = {
    "workflow": (
        "Create a branch-bound contract with task_create, complete dependencies, then use "
        "task_node_apply_batch with the exact owner and current revision. Inspect the task "
        "and its immutable operation rows before review."
    ),
    "scope": (
        "The first contract version enforces whole-document scope. It excludes reserved "
        "build, test, and task metadata from allowed documents. Symbol-level scope requires "
        "compiler-owned semantic identities and is not inferred by Jacquard."
    ),
    "dependencies": (
        "Every dependency must exist in the same exact revision, dependency graphs must be "
        "acyclic, and task-bound editing requires all dependencies to have status complete."
    ),
    "ownership": (
        "Only the declared owner may run task_node_apply_batch or change task status. The "
        "actor and contract identity are retained in every task-bound operation payload."
    ),
    "boundary": (
        "A task contract constrains the explicit task-bound edit path. It does not prove "
        "correctness, test completion, merge readiness, or that unrelated ordinary tools "
        "were never used. Review immutable operations and required evidence separately."
    ),
}


def weave_help(topic: str = "workflow") -> dict[str, Any]:
    """Extend runtime help with revisioned task-contract guidance."""

    if topic == "task_contracts":
        return {"ok": True, "topic": topic, "help": deepcopy(_TOPIC)}

    response = _base.weave_help(topic)
    help_value = deepcopy(response["help"])
    tools = help_value.setdefault("tools", {})
    if topic in {"workflow", "write", "resume"}:
        tools["task_create"] = (
            "Create a revisioned branch-bound work contract with explicit document scope."
        )
        tools["task_get"] = "Read one full task contract at a branch head or exact revision."
        tools["task_list"] = "Page bounded task summaries from one exact revision."
        tools["task_status_set"] = "Publish one owner-authorized task status transition."
        tools["task_node_apply_batch"] = (
            "Apply a bounded batch only when owner, branch, scope, status, and dependencies pass."
        )
    return {**response, "help": help_value}
