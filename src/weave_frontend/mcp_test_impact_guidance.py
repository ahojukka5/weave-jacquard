"""Runtime guidance for exact-revision structural behavioral-test impact plans."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from . import mcp_test_batch_guidance as _base

_IMPACT_INSTRUCTION = """
Use test_impact_plan to compare one explicit base revision with one exact target
revision before choosing a batch. It executes nothing. A surviving test is a
structural candidate only when its definition changed, its referenced build
target changed, or one of that target's source documents changed. The plan also
reports removed tests, uncovered changed sources, and changed targets with no
surviving tests. Pagination is lexical only and plan_id is stable across pages.
Only a complete unpaginated selection includes replayable test_batch_run
arguments; never execute a partial page as though it were the full plan.
""".strip()

INSTRUCTIONS = f"{_base.INSTRUCTIONS}\n{_IMPACT_INSTRUCTION}"

_IMPACT_TOPIC: dict[str, Any] = {
    "compare": (
        "Provide base_revision_id and preferably target_revision_id. If target_revision_id is "
        "omitted, Jacquard captures the current branch head once and returns its exact ID."
    ),
    "rules": (
        "Candidates are surviving tests whose definition changed, referenced build-target "
        "definition changed, or referenced source document changed."
    ),
    "gaps": (
        "The plan reports removed tests, removed build targets, changed source documents with "
        "no surviving test coverage, and changed build targets referenced by no tests."
    ),
    "pagination": (
        "Impacted tests are paged lexically with stable plan_id and next_after_name. Lexical "
        "order is not priority, urgency, cost, or expected failure probability."
    ),
    "batch": (
        "A replayable test_batch_run call appears only when the first page contains the entire "
        "non-empty candidate selection. Collect every page explicitly otherwise."
    ),
    "boundary": (
        "The plan runs no compiler or test, claims no correctness, and cannot prove complete "
        "semantic coverage. It is structural evidence for selecting an explicit batch."
    ),
}


def weave_help(topic: str = "workflow") -> dict[str, Any]:
    """Extend runtime help with structural test-impact guidance."""

    if topic == "test_impact":
        return {"ok": True, "topic": topic, "help": deepcopy(_IMPACT_TOPIC)}

    response = _base.weave_help(topic)
    help_value = deepcopy(response["help"])
    if topic == "read":
        help_value["tools"]["test_impact_plan"] = (
            "Page non-executing structural test candidates between exact revisions."
        )
    return {**response, "help": help_value}
