"""Production MCP registration for runtime identity and capabilities."""

from __future__ import annotations

from typing import Any

from .mcp_build import compiler_bridge
from .mcp_server import _result, mcp, workspace
from .mcp_test_runs import test_runs
from .runtime_container import runtime_config, runtime_service, runtime_services
from .runtime_identity import RuntimeIdentityService


def _application_manifest() -> dict[str, Any]:
    """Read the completed public application manifest lazily after composition."""

    from weave_jacquard.mcp_build import PUBLIC_APPLICATION_MANIFEST

    return dict(PUBLIC_APPLICATION_MANIFEST)


class RuntimeIdentityWithServices:
    """Bind the stable typed service composition into normal runtime identity."""

    def __init__(self, identity: RuntimeIdentityService) -> None:
        self.identity = identity

    def report(self) -> dict[str, Any]:
        result = self.identity.report()
        result.pop("runtime_id", None)
        result["service_graph"] = runtime_services().service_manifest(
            include_state=False
        )
        result["runtime_id"] = RuntimeIdentityService._hash_json(result)
        return result


@runtime_service(
    "runtime_identity",
    depends_on=("workspace", "compiler_bridge"),
)
def runtime_identities() -> RuntimeIdentityWithServices:
    """Return the runtime-owned identity service."""

    runs = test_runs()
    return RuntimeIdentityWithServices(
        RuntimeIdentityService(
            workspace(),
            compiler_bridge(),
            runs.sandbox,
            _application_manifest,
            environ=runtime_config().configured_environment,
        )
    )


@mcp.tool()
def runtime_identity() -> dict[str, Any]:
    """Report exact runtime identity with configuration values redacted."""

    return _result(runtime_identities().report)
