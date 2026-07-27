"""Runtime guidance for virtual merge-candidate behavioral-test impact plans."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from . import mcp_test_impact_guidance as _base

_MERGE_IMPACT_INSTRUCTION = """
Use branch_merge_test_impact only for one structurally clean exact merge preview.
It compares the committed target head with the preview's in-memory merged state,
then applies the same test-definition, build-target, and source-change rules as
revision impact planning. A supplied preview_id must still match current target
and source heads. Conflicted previews stop before impact analysis. Candidate test
definitions are virtual and have no committed revision. Ordinary test_batch_run is
incompatible with that uncommitted subject. A complete non-empty first page emits
explicit branch_merge_test_batch_run arguments for the exact preview; partial and
continuation pages emit no execution call. Planning itself runs nothing and
publishes no merge.
""".strip()

INSTRUCTIONS = f"{_base.INSTRUCTIONS}\n{_MERGE_IMPACT_INSTRUCTION}"

_TOPIC: dict[str, Any] = {
    "preview": (
        "branch_merge_test_impact binds target head, source head, common base, preview_id, and "
        "merged_root_hash. Pass preview_id to reject head or candidate drift."
    ),
    "rules": (
        "Surviving virtual-candidate tests are selected only when their definition, referenced "
        "build target, or referenced source documents differ from the committed target head."
    ),
    "conflicts": (
        "A structurally conflicted preview returns a merge conflict before any test-impact "
        "candidate evidence is produced."
    ),
    "virtual": (
        "Candidate definition hashes identify in-memory merged metadata. They have no committed "
        "revision_id and cannot be read with ordinary revision-bound test_target_get."
    ),
    "execution": (
        "A complete non-empty first page emits branch_merge_test_batch_run with the exact "
        "preview_id and full lexical candidate list. Partial, continuation, and empty pages emit "
        "candidate_execution=null. Ordinary revision-bound test_batch_run remains incompatible."
    ),
    "pagination": (
        "Candidate tests are paged lexically under one stable plan_id. Lexical order is not "
        "priority, urgency, cost, or expected failure probability."
    ),
    "boundary": (
        "The plan runs no compiler or test, publishes no merge, claims no correctness, and "
        "does not prove complete semantic coverage."
    ),
}


def weave_help(topic: str = "workflow") -> dict[str, Any]:
    """Extend runtime help with virtual merge-candidate impact guidance."""

    if topic == "merge_test_impact":
        return {"ok": True, "topic": topic, "help": deepcopy(_TOPIC)}

    response = _base.weave_help(topic)
    help_value = deepcopy(response["help"])
    if topic == "read":
        help_value["tools"]["branch_merge_test_impact"] = (
            "Page non-executing structural test candidates for an exact clean merge preview."
        )
    return {**response, "help": help_value}
