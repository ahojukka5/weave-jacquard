"""Production MCP registration for runtime identity and capabilities."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from .mcp_build import compiler_bridge
from .mcp_server import _result, mcp, workspace
from .mcp_test_runs import test_runs
from .runtime_identity import RuntimeIdentityService


def _application_manifest() -> dict[str, Any]:
    """Read the completed public application manifest lazily after composition."""

    from weave_jacquard.mcp_build import PUBLIC_APPLICATION_MANIFEST

    return dict(PUBLIC_APPLICATION_MANIFEST)


@lru_cache(maxsize=1)
def runtime_identities() -> RuntimeIdentityService:
    """Return the shared runtime identity service."""

    runs = test_runs()
    return RuntimeIdentityService(
        workspace(),
        compiler_bridge(),
        runs.sandbox,
        _application_manifest,
    )


def install_capability() -> None:
    """Discard stale runtime identity dependencies during recomposition."""

    runtime_identities.cache_clear()


@mcp.tool()
def runtime_identity() -> dict[str, Any]:
    """Report exact runtime identity with configuration values redacted."""

    return _result(runtime_identities().report)
