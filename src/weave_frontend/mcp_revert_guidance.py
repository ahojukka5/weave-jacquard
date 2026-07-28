"""Runtime guidance for conflict-aware immutable branch reverts."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from . import mcp_evidence_guidance as _base

_REVERT_INSTRUCTION = """
Use branch_revert_preview before branch_revert. A revert applies the inverse of one
selected first-parent revision onto the current branch through the stable-ID
three-way merge engine. Independent later edits survive; overlapping later edits
become conflicts. Publication always requires the exact preview_id and creates a
new revision. It never resets a branch or rewrites history. Revert preview validates
structural, build-target, test-target, and task-contract integrity, but it does not
run compiler validation, behavioral tests, merge policy admission, or human review.
""".strip()

INSTRUCTIONS = f"{_base.INSTRUCTIONS}\n{_REVERT_INSTRUCTION}"

_REVERT_TOPIC: dict[str, Any] = {
    "workflow": (
        "Select one revision from the current branch's first-parent history, call "
        "branch_revert_preview, inspect conflicts and document_changes, then call "
        "branch_revert with the exact preview_id."
    ),
    "semantics": (
        "Jacquard treats the selected revision as the merge base, the current branch head "
        "as ours, and the selected revision's first parent as the inverse state."
    ),
    "history": (
        "A successful revert creates one new single-parent revision whose parent is the "
        "current branch head. It never resets a branch, deletes revisions, or rewrites "
        "existing history."
    ),
    "integrity": (
        "Preview rejects prospective states with dangling build-target source documents, "
        "test-target bindings, task document scopes, task dependencies, or required tests."
    ),
    "boundary": (
        "Revert preview verifies structural and project-metadata integrity only. It does not "
        "run the compiler, tests, policy admission, approval, or readiness checks."
    ),
}

_RUNTIME_TOPIC: dict[str, Any] = {
    "tool": "runtime_identity",
    "purpose": (
        "Correlate one live server with its application contract, package and SDK versions, "
        "database policy, compiler identity, and strict sandbox identity."
    ),
    "redaction": (
        "Configuration values and executable paths are not returned. Domain-separated "
        "opaque IDs allow equality comparison without exposing raw values."
    ),
    "stability": (
        "Repeated calls against an unchanged process return the same content-derived "
        "runtime_id because the report contains no timestamp or random value."
    ),
    "boundary": (
        "Runtime identity is diagnostic evidence, not proof that the server passed full "
        "qualification."
    ),
}

_STORAGE_TOPIC: dict[str, Any] = {
    "tool": "artifact_storage_report",
    "purpose": (
        "Measure complete logical bytes and entry counts across committed builds, virtual "
        "candidate builds, test evidence, qualifications, and attestations."
    ),
    "redaction": (
        "Storage paths are replaced by content-derived root and lock IDs. Family names, "
        "counts, limits, quota state, and nested-root ownership remain visible."
    ),
    "bounds": (
        "The scan fails rather than truncates when root count, total entries, or directory "
        "depth exceeds its explicit ceiling. Symlinks are counted but never followed."
    ),
    "quota": (
        "WEAVE_ARTIFACT_MAX_BYTES enables one interprocess logical-byte admission ceiling "
        "across all six production artifact publishers."
    ),
    "boundary": (
        "Quota refusal prevents new retained publication but does not implement retention, "
        "garbage collection, physical-block limits, or database-size policy."
    ),
}


def weave_help(topic: str = "workflow") -> dict[str, Any]:
    """Extend runtime help with revert, storage, and runtime identity guidance."""

    if topic == "revert":
        return {"ok": True, "topic": topic, "help": deepcopy(_REVERT_TOPIC)}
    if topic == "runtime":
        return {"ok": True, "topic": topic, "help": deepcopy(_RUNTIME_TOPIC)}
    if topic == "storage":
        return {"ok": True, "topic": topic, "help": deepcopy(_STORAGE_TOPIC)}

    response = _base.weave_help(topic)
    help_value = deepcopy(response["help"])
    if topic in {"workflow", "write", "read", "history"}:
        tools = help_value.setdefault("tools", {})
        tools["branch_revert_preview"] = (
            "Preview one conflict-aware inverse without moving the branch."
        )
        tools["branch_revert"] = (
            "Publish the exact reviewed inverse as a new immutable revision."
        )
    if topic in {"workflow", "read"}:
        tools = help_value.setdefault("tools", {})
        tools["artifact_storage_report"] = (
            "Report bounded retained usage and aggregate publication quota state."
        )
        tools["runtime_identity"] = (
            "Report the exact live application, compiler, database, and sandbox identity."
        )
    return {**response, "help": help_value}
