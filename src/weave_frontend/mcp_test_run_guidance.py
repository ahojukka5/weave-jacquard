"""Runtime guidance for strict sandboxed behavioral test execution."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from . import mcp_test_guidance as _base

_RUN_INSTRUCTION = """
Call sandbox_capabilities before execution. test_run never falls back to an
ordinary host subprocess: it requires a successful bubblewrap isolation probe,
denied networking, read-only runtime mounts, ephemeral tmpfs writes, dropped
capabilities, and enforced time, memory, output, and file limits. Pin
revision_id whenever reviewing prepared work. Every run binds the exact revision,
test definition_hash, retained build, executable hash, and sandbox policy hash,
then publishes an immutable verified manifest. A failed behavioral assertion is
valid run evidence with passed=false; SANDBOX_UNAVAILABLE and TEST_BUILD_FAILED
publish no behavioral result. Use test_run_get and bounded
test_run_output_page reads instead of server-local artifact paths.
""".strip()

INSTRUCTIONS = f"{_base.INSTRUCTIONS}\n{_RUN_INSTRUCTION}"

_RUN_TOPIC: dict[str, Any] = {
    "probe": (
        "Call sandbox_capabilities first. available=false means execution is refused; "
        "Jacquard never silently substitutes plain subprocess execution."
    ),
    "execute": (
        "Use test_run with project, test_target, branch, and preferably revision_id. The "
        "referenced named build target is rebuilt or reused at that exact revision."
    ),
    "isolation": (
        "The bubblewrap backend creates new user, mount, PID, network, IPC, and UTS "
        "namespaces; drops capabilities; exposes runtime paths read-only; and provides only "
        "ephemeral /tmp and /work writes."
    ),
    "limits": (
        "The stored test definition controls wall timeout, address space, CPU time, captured "
        "output, generated-file size, open files, process count, and core dumps."
    ),
    "evidence": (
        "A run manifest binds revision_id, definition_hash, build_id, executable hash, "
        "sandbox policy hash, expected hashes, observed hashes, assertions, and pass status."
    ),
    "failures": (
        "passed=false is immutable behavioral evidence. SANDBOX_UNAVAILABLE or "
        "TEST_BUILD_FAILED is infrastructure/build refusal and publishes no run manifest."
    ),
    "outputs": (
        "Use test_run_output_page for verified bounded stdout/stderr bytes. It returns base64, "
        "UTF-8 text when valid, continuation, total bytes, and stream/manifest hashes."
    ),
    "boundary": (
        "The current backend reports seccomp=false. Namespace and resource isolation are "
        "explicitly reported; do not infer protections absent from sandbox_capabilities."
    ),
}


def weave_help(topic: str = "workflow") -> dict[str, Any]:
    """Extend existing runtime help with strict test-run guidance."""

    if topic == "test_runs":
        return {"ok": True, "topic": topic, "help": deepcopy(_RUN_TOPIC)}

    response = _base.weave_help(topic)
    help_value = deepcopy(response["help"])
    if topic == "read":
        help_value["tools"]["sandbox_capabilities"] = (
            "Probe strict sandbox availability and inspect the exact enforced policy."
        )
        help_value["tools"]["test_run_get"] = (
            "Read and verify one immutable sandboxed test-run manifest."
        )
        help_value["tools"]["test_run_output_page"] = (
            "Read verified bounded stdout or stderr bytes from one retained run."
        )
    elif topic == "build":
        help_value["tools"]["test_run"] = (
            "Build and execute one exact revisioned behavioral test in the strict sandbox."
        )
    return {**response, "help": help_value}
