from __future__ import annotations

from types import SimpleNamespace

import pytest

import weave_frontend.mcp_concurrent_nodes as concurrent_nodes
from weave_frontend.context_capability_installers import (
    install_production_capability,
)
from weave_frontend.mcp_capabilities import ApplicationContext
from weave_frontend.runtime import (
    RuntimeClosedError,
    RuntimeConfig,
    RuntimeServices,
    bind_application_runtime,
    runtime_services,
)


def _runtime(database: str) -> RuntimeServices:
    return RuntimeServices(RuntimeConfig.from_environ({"WEAVE_DB_PATH": database}))


def test_public_application_owns_exact_process_context() -> None:
    from weave_jacquard import mcp_build as public_entrypoint

    assert public_entrypoint.PUBLIC_APP.context.server is public_entrypoint.mcp
    assert public_entrypoint.PUBLIC_APP.context.runtime is runtime_services()


def test_foundational_installer_uses_supplied_runtime() -> None:
    runtime = _runtime("foundational-context.db")
    context = ApplicationContext(server=SimpleNamespace(), runtime=runtime)

    with bind_application_runtime(runtime):
        assert install_production_capability(
            "concurrent_nodes",
            concurrent_nodes,
            context,
        )

    assert context.runtime is runtime


def test_application_context_rejects_closed_runtime() -> None:
    runtime = _runtime("closed-context.db")
    runtime.close()

    with pytest.raises(RuntimeClosedError, match="closed runtime"):
        ApplicationContext(server=SimpleNamespace(), runtime=runtime)
