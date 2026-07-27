"""Runtime guidance for tested-merge state-identity attestations."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from . import mcp_merge_candidate_test_guidance as _base

_ATTESTATION_INSTRUCTION = """
After publishing a branch merge that was previously qualified as a virtual
candidate, call tested_merge_attest with the retained qualification_id and the
new merged revision_id. Jacquard verifies the same project, exact target/source
parents, and exact merged root hash, then retains a content-derived attestation.
The attestation preserves passed, failed, or incomplete qualification status; it
never upgrades failed evidence to readiness. State identity does not prove test
coverage, policy admission, human approval, or production readiness.
""".strip()

INSTRUCTIONS = f"{_base.INSTRUCTIONS}\n{_ATTESTATION_INSTRUCTION}"

_TOPIC: dict[str, Any] = {
    "workflow": (
        "Run and retain branch_merge_test_batch_run evidence, publish the exact preview through "
        "branch_merge, then call tested_merge_attest with qualification_id and merged_revision_id."
    ),
    "identity": (
        "The attestation requires the committed revision project, parent1 target head, parent2 "
        "source head, and root hash to match the qualification subject exactly."
    ),
    "statuses": (
        "Passing, failed, and incomplete qualifications can all be attested truthfully. The "
        "original aggregate status and counts are preserved without reinterpretation."
    ),
    "inspection": (
        "Use tested_merge_attestation_get to reverify the qualification manifest, merge parents, "
        "root hash, content-derived attestation ID, and interpretation flags."
    ),
    "boundary": (
        "An attestation proves only that the exact qualified candidate state was committed. It "
        "does not prove complete coverage, unselected behavior, policy admission, approval, or "
        "readiness."
    ),
}


def weave_help(topic: str = "workflow") -> dict[str, Any]:
    """Extend runtime help with tested-merge provenance guidance."""

    if topic == "tested_merge_attestations":
        return {"ok": True, "topic": topic, "help": deepcopy(_TOPIC)}

    response = _base.weave_help(topic)
    help_value = deepcopy(response["help"])
    tools = help_value.setdefault("tools", {})
    if topic in {"workflow", "test_batches"}:
        tools["tested_merge_attest"] = (
            "Prove that a committed two-parent merge exactly equals a retained tested candidate."
        )
        tools["tested_merge_attestation_get"] = (
            "Read and reverify one immutable tested-merge state-identity attestation."
        )
    return {**response, "help": help_value}
