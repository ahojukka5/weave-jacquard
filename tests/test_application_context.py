from __future__ import annotations

from types import SimpleNamespace

import pytest

import weave_frontend.mcp_concurrent_nodes as concurrent_nodes
from weave_frontend.mcp_capabilities import ApplicationContext
from weave_frontend.runtime_config import RuntimeConfig
from weave_frontend.runtime_container import (
    RuntimeClosedError,
    RuntimeServices,
    runtime_services,
)


def _runtime(database: str) -> RuntimeServices:
    return RuntimeServices(
        RuntimeConfig.from_environ({"WEAVE_DB_PATH": database})
    )


def test_public_application_owns_exact_process_context() -> None:
    from weave_jacquard import mcp_build as public_entrypoint

    assert public_entrypoint.PUBLIC_APP.context.server is public_entrypoint.mcp
    assert public_entrypoint.PUBLIC_APP.context.runtime is runtime_services()


def test_foundational_installer_uses_supplied_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime("foundational-context.db")
    context = ApplicationContext(server=SimpleNamespace(), runtime=runtime)

    monkeypatch.setattr(
        concurrent_nodes,
        "runtime_services",
        lambda: pytest.fail("process runtime must not be consulted"),
    )

    concurrent_nodes.install_capability(context)

    assert context.runtime is runtime


def test_application_context_rejects_closed_runtime() -> None:
    runtime = _runtime("closed-context.db")
    runtime.close()

    with pytest.raises(RuntimeClosedError, match="closed runtime"):
        ApplicationContext(server=SimpleNamespace(), runtime=runtime)
