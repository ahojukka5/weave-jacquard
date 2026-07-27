from __future__ import annotations

from types import SimpleNamespace

from weave_frontend import mcp_revert
from weave_frontend.revert import RevertService


def test_revert_service_factory_composes_shared_services(monkeypatch) -> None:
    workspace = SimpleNamespace()
    previews = SimpleNamespace()
    monkeypatch.setattr(mcp_revert, "workspace", lambda: workspace)
    monkeypatch.setattr(mcp_revert, "merge_previews", lambda: previews)
    mcp_revert.reverts.cache_clear()

    first = mcp_revert.reverts()
    second = mcp_revert.reverts()
    assert isinstance(first, RevertService)
    assert first is second
    assert first.workspace is workspace
    assert first.previews is previews

    mcp_revert.install_capability()
    replacement = mcp_revert.reverts()
    assert replacement is not first
    assert replacement.workspace is workspace
    assert replacement.previews is previews
    mcp_revert.reverts.cache_clear()
