"""Runtime guidance for bounded verified revision evidence graphs."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from . import mcp_task_guidance as _base

_EVIDENCE_INSTRUCTION = """
Use revision_evidence_page when a retained build, test run, test batch, or
state-identity attestation ID is no longer in context. Select one exact project
revision and one evidence kind, replay catalog_id across pages when stable live
membership matters, and follow typed detail tools for full verified manifests.
Evidence discovery reports only retained artifacts; absence does not prove that a
check never ran, and presence does not prove complete coverage, policy admission,
approval, or readiness.
""".strip()

INSTRUCTIONS = f"{_base.INSTRUCTIONS}\n{_EVIDENCE_INSTRUCTION}"

_TOPIC: dict[str, Any] = {
    "workflow": (
        "Call revision_evidence_page with one exact revision and one kind: build, "
        "test_run, test_batch, or tested_merge_attestation. Follow next_after_id and "
        "replay catalog_id for stable membership."
    ),
    "graph": (
        "Every page includes the immutable revision subject node plus verified evidence "
        "nodes and typed edges. Edges may reference nodes discoverable from another kind."
    ),
    "integrity": (
        "Each returned member passes its existing build, run, batch, qualification, or "
        "attestation get verifier. Corrupt members are returned only as evidence IDs and "
        "bounded error codes; server-local paths are never exposed."
    ),
    "boundary": (
        "The graph covers retained artifacts in immutable stores only. Merge preview and "
        "preflight responses are intentionally non-persistent, and graph absence or presence "
        "does not establish complete coverage, policy admission, approval, or readiness."
    ),
}


def weave_help(topic: str = "workflow") -> dict[str, Any]:
    """Extend runtime help with retained revision-evidence discovery."""

    if topic == "revision_evidence":
        return {"ok": True, "topic": topic, "help": deepcopy(_TOPIC)}

    response = _base.weave_help(topic)
    help_value = deepcopy(response["help"])
    if topic in {"workflow", "read", "build", "test_batches", "tested_merge_attestations"}:
        tools = help_value.setdefault("tools", {})
        tools["revision_evidence_page"] = (
            "Page verified retained evidence linked to one exact immutable revision."
        )
    return {**response, "help": help_value}
