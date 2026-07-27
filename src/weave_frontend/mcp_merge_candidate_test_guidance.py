"""Runtime guidance for strict behavioral execution of virtual merge candidates."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from . import mcp_merge_test_impact_guidance as _base

_EXECUTION_INSTRUCTION = """
Use branch_merge_test_batch_run only with an explicit unique ordered test list and
one exact clean preview_id. Jacquard captures the virtual merged state once,
builds named targets into separate content-derived candidate artifacts, and runs
each selected test through the reported strict sandbox. Candidate builds and run
evidence bind target/source heads, common base, preview_id, merged_root_hash,
definition hashes, compiler hash, executable hash, sandbox policy, and limits.
Behavioral failures remain evidence. Build failures make the batch incomplete.
Ordinary test_batch_run is incompatible with an uncommitted merge candidate;
use branch_merge_test_batch_run for this exact preview-bound evidence instead.
Execution publishes no merge and advances no branch. Always use branch_merge with
the same preview_id separately; it will reject stale heads.
""".strip()

INSTRUCTIONS = f"{_base.INSTRUCTIONS}\n{_EXECUTION_INSTRUCTION}"

_TOPIC: dict[str, Any] = {
    "selection": (
        "branch_merge_test_batch_run requires an explicit unique ordered list of one to 64 "
        "virtual-candidate test targets. It never discovers, expands, ranks, or reorders tests."
    ),
    "subject": (
        "Every build and qualification binds exact target/source heads, common base, preview_id, "
        "merged_root_hash, and committed_revision_id=null."
    ),
    "builds": (
        "Candidate targets are compiled into separately verified content-derived artifacts. Tests "
        "sharing one build target reuse the same exact executable."
    ),
    "sandbox": (
        "Execution uses the authoritative sandbox_capabilities policy. Missing strict isolation "
        "rejects the whole request; there is no unrestricted host fallback."
    ),
    "evidence": (
        "Passing and failed assertions retain immutable output evidence. Candidate build failures "
        "remain verified build artifacts and make the aggregate qualification incomplete."
    ),
    "inspection": (
        "Use merge_candidate_build_get and merge_candidate_build_diagnostics_page for build "
        "evidence, merge_candidate_test_batch_get for aggregate evidence, and "
        "merge_candidate_test_output_page for bounded stdout or stderr."
    ),
    "publication": (
        "Candidate execution publishes no merge and advances no branch. A recorded head-stability "
        "flag is evidence only; branch_merge must still replay the exact preview guard."
    ),
    "boundary": (
        "Passing selected tests does not prove complete semantic coverage, merge admission, human "
        "approval, or anything about unselected tests."
    ),
}


def weave_help(topic: str = "workflow") -> dict[str, Any]:
    """Extend runtime help with virtual-candidate execution guidance."""

    if topic == "merge_candidate_tests":
        return {"ok": True, "topic": topic, "help": deepcopy(_TOPIC)}

    response = _base.weave_help(topic)
    help_value = deepcopy(response["help"])
    tools = help_value.setdefault("tools", {})
    if topic == "build":
        tools["branch_merge_build_target"] = (
            "Build one named target from an exact clean virtual merge candidate."
        )
        tools["merge_candidate_build_get"] = (
            "Read one verified candidate-build manifest without server-local paths."
        )
        tools["merge_candidate_build_diagnostics_page"] = (
            "Page verified mapped diagnostics from one candidate build."
        )
    if topic == "test_batches":
        tools["branch_merge_test_batch_run"] = (
            "Run an explicit ordered test list on one exact virtual merge candidate."
        )
        tools["merge_candidate_test_batch_get"] = (
            "Read and verify retained aggregate virtual-candidate evidence."
        )
        tools["merge_candidate_test_output_page"] = (
            "Read bounded verified candidate stdout or stderr."
        )
    return {**response, "help": help_value}
