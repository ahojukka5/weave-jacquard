"""Runtime guidance for bounded explicit behavioral-test batches."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from . import mcp_test_run_guidance as _base

_BATCH_INSTRUCTION = """
Use test_batch_run only with an explicit bounded unique test_targets list. Caller
order is preserved as structural input and is not priority or automatic
selection. Jacquard resolves every definition at one captured revision before
execution, probes the strict sandbox before the first run, retains each
individual run independently, and publishes one immutable aggregate manifest.
Behavioral failures remain valid evidence; per-test domain errors make the batch
incomplete without erasing successful sibling evidence. Use test_batch_get to
verify the aggregate and every referenced run manifest.
""".strip()

INSTRUCTIONS = f"{_base.INSTRUCTIONS}\n{_BATCH_INSTRUCTION}"

_BATCH_TOPIC: dict[str, Any] = {
    "selection": (
        "test_batch_run requires 1 to 64 unique explicit test-target names. It never expands "
        "tags, discovers tests implicitly, ranks tests, or changes caller order."
    ),
    "revision": (
        "All definitions are resolved before execution from one exact revision_id. A missing "
        "definition rejects the whole request before any test starts."
    ),
    "execution": (
        "The strict sandbox is probed once before execution. Individual tests then publish "
        "their normal immutable run evidence in caller order."
    ),
    "outcomes": (
        "Batch status is passed when all tests pass, failed when behavioral evidence fails, "
        "and incomplete when one or more tests return independent domain errors."
    ),
    "errors": (
        "Per-test build or validation errors are retained in the batch result and do not erase "
        "sibling run evidence. SANDBOX_UNAVAILABLE rejects the batch as a whole."
    ),
    "evidence": (
        "The aggregate manifest binds project, branch, revision, ordered selection, every "
        "definition_hash, sandbox policy hash, counts, outcomes, run IDs, and run hashes."
    ),
    "boundary": (
        "A batch is orchestration evidence, not a project revision, merge admission, test "
        "selection policy, priority signal, or proof about unselected tests."
    ),
}


def weave_help(topic: str = "workflow") -> dict[str, Any]:
    """Extend runtime help with explicit test-batch guidance."""

    if topic == "test_batches":
        return {"ok": True, "topic": topic, "help": deepcopy(_BATCH_TOPIC)}

    response = _base.weave_help(topic)
    help_value = deepcopy(response["help"])
    if topic == "read":
        help_value["tools"]["test_batch_get"] = (
            "Read and verify one immutable explicit test-batch manifest and every run link."
        )
    elif topic == "build":
        help_value.setdefault("tools", {})["test_batch_run"] = (
            "Run one explicit bounded ordered behavioral-test set at an exact revision."
        )
    return {**response, "help": help_value}
