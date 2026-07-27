"""Runtime guidance for revisioned behavioral test definitions."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from . import mcp_merge_train_guidance as _base

_TEST_INSTRUCTION = """
Use test_target_set to define expected behavior against one existing named build
target at an exact revision. Test definitions are immutable project metadata:
they include arguments, controlled stdin, exact expected exit/stdout/stderr
values, bounded resource limits, an isolated filesystem policy, and denied
network access. Writes and exact reads return a deterministic definition_hash.
Use bounded lexical test_target_list summaries for discovery and test_target_get
for full content at the exact reviewed revision. They do not execute programs. A
later sandbox runner must bind its evidence to that same revision and definition
hash; do not treat the existence of a test target as proof that it passed.
""".strip()

INSTRUCTIONS = f"{_base.INSTRUCTIONS}\n{_TEST_INSTRUCTION}"

_TEST_TOPIC: dict[str, Any] = {
    "define": (
        "Use test_target_set to publish one revisioned behavioral contract bound to an "
        "existing named build target. Pass expected_revision_id for reviewed writes."
    ),
    "expectations": (
        "Definitions contain ordered arguments, controlled stdin, exact expected exit code, "
        "stdout and stderr, resource bounds, and optional tags."
    ),
    "identity": (
        "test_target_set and test_target_get return definition_hash, a deterministic hash of "
        "the exact structural definition at revision_id."
    ),
    "discovery": (
        "test_target_list returns bounded lexical summaries with totals, truncation, "
        "next_after_name continuation, expectation byte counts, and exact detail calls."
    ),
    "sandbox": (
        "Every definition fixes network_policy='deny' and filesystem_policy='isolated'. "
        "These are future runner requirements, not evidence that execution occurred."
    ),
    "revision": (
        "Use test_target_get or test_target_list with revision_id to inspect the exact test "
        "definitions associated with a reviewed program state."
    ),
    "metadata": (
        "Test definitions are reserved structural metadata. They merge and remain auditable, "
        "but are excluded from compiler source sets and uncovered-source calculations."
    ),
    "execution": (
        "This capability defines tests only. It exposes no program execution or pass/fail "
        "claim. Immutable sandboxed run evidence is a separate later capability."
    ),
}


def weave_help(topic: str = "workflow") -> dict[str, Any]:
    """Extend existing runtime help with revisioned test-definition guidance."""

    if topic == "test_targets":
        return {"ok": True, "topic": topic, "help": deepcopy(_TEST_TOPIC)}

    response = _base.weave_help(topic)
    help_value = deepcopy(response["help"])
    if topic == "read":
        help_value["tools"]["test_target_get"] = (
            "Read one full hashed behavioral test definition at a branch head or exact revision."
        )
        help_value["tools"]["test_target_list"] = (
            "Page bounded lexical test summaries at a branch head or exact revision."
        )
    elif topic == "write":
        help_value["tools"]["test_target_set"] = (
            "Publish one race-safe hashed sandbox-ready test definition against a named target."
        )
        help_value["tools"]["test_target_delete"] = (
            "Delete one test definition through an immutable compare-and-set revision."
        )
    return {**response, "help": help_value}
