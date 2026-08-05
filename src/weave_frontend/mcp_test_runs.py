"""Production MCP registration for strict sandboxed behavioral test runs."""

from __future__ import annotations

from typing import Any

from .mcp_build import build_targets, compiler_bridge
from .mcp_server import _result, mcp, workspace
from .mcp_test_targets import test_targets
from .runtime import RuntimeBubblewrapSandbox, TestRunService, runtime_config, runtime_service
from .test_runs import DEFAULT_TEST_RUN_OUTPUT_PAGE_BYTES


@runtime_service(
    "test_runs",
    depends_on=(
        "workspace",
        "build_targets",
        "test_targets",
        "compiler_bridge",
    ),
)
def test_runs() -> TestRunService:
    """Return the shared immutable sandboxed test-run service."""

    config = runtime_config()
    return TestRunService(
        workspace(),
        build_targets(),
        test_targets(),
        compiler_bridge(),
        RuntimeBubblewrapSandbox.from_config(config),
        run_root=config.test_run_root,
    )


def _public_run(result: dict[str, Any]) -> dict[str, Any]:
    """Remove server-local storage paths from the agent-facing run evidence."""

    return {key: value for key, value in result.items() if key != "artifact_paths"}


@mcp.tool()
def sandbox_capabilities() -> dict[str, Any]:
    """Probe whether strict sandbox execution is available and report its policy."""

    return _result(test_runs().capabilities)


@mcp.tool()
def test_run(
    project: str,
    test_target: str,
    branch: str = "main",
    revision_id: str | None = None,
) -> dict[str, Any]:
    """Build and execute one exact revisioned test in the strict sandbox."""

    return _result(
        lambda: _public_run(
            test_runs().run(
                project,
                test_target,
                branch=branch,
                revision_id=revision_id,
            )
        )
    )


@mcp.tool()
def test_run_get(run_id: str) -> dict[str, Any]:
    """Read and verify one immutable sandboxed test-run manifest."""

    return _result(lambda: _public_run(test_runs().get(run_id)))


@mcp.tool()
def test_run_output_page(
    run_id: str,
    stream: str,
    start_byte: int = 0,
    max_bytes: int = DEFAULT_TEST_RUN_OUTPUT_PAGE_BYTES,
) -> dict[str, Any]:
    """Read a verified bounded stdout or stderr byte page from one test run."""

    return _result(
        lambda: test_runs().output_page(
            run_id,
            stream,
            start_byte=start_byte,
            max_bytes=max_bytes,
        )
    )
