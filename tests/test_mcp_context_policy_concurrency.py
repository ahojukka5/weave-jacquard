from __future__ import annotations

from typing import Any

from weave_frontend import mcp_concurrent_context, mcp_preflight
from weave_frontend.merges import ConcurrentMergePolicyRegistry as MergePolicyRegistry


class _Workspace:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def add_context(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((args, kwargs))
        return {
            "revision_id": "revision-new",
            "base_revision_id": kwargs["expected_revision_id"],
            "document_id": "document-1",
        }


class _Policies:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def set(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((args, kwargs))
        return {
            "revision_id": "revision-new",
            "base_revision_id": kwargs["expected_revision_id"],
            "document_id": "document-1",
        }


def test_context_tool_forwards_expected_revision_and_author(monkeypatch) -> None:
    workspace = _Workspace()
    monkeypatch.setattr(mcp_concurrent_context, "workspace", lambda: workspace)

    response = mcp_concurrent_context.context_add(
        "demo",
        "main",
        "document",
        "main.weave",
        "Invariant",
        "Body",
        expected_revision_id="revision-base",
        author="context-agent",
    )

    assert response["ok"] is True
    assert response["result"]["base_revision_id"] == "revision-base"
    assert workspace.calls == [
        (
            ("demo", "main"),
            {
                "scope_kind": "document",
                "scope_name": "main.weave",
                "title": "Invariant",
                "body": "Body",
                "expected_revision_id": "revision-base",
                "author": "context-agent",
            },
        )
    ]


def test_policy_tool_forwards_expected_revision_and_author(monkeypatch) -> None:
    policies = _Policies()
    monkeypatch.setattr(
        mcp_concurrent_context._preflight,
        "merge_policies",
        lambda: policies,
    )

    response = mcp_concurrent_context.merge_policy_set(
        "demo",
        "main",
        require_preflight=True,
        require_affected_validation=True,
        allow_uncovered_documents=False,
        max_affected_targets=9,
        expected_revision_id="revision-base",
        author="policy-agent-2",
    )

    assert response["ok"] is True
    assert response["result"]["base_revision_id"] == "revision-base"
    assert policies.calls == [
        (
            ("demo", "main"),
            {
                "require_preflight": True,
                "require_affected_validation": True,
                "allow_uncovered_documents": False,
                "max_affected_targets": 9,
                "expected_revision_id": "revision-base",
                "author": "policy-agent-2",
            },
        )
    ]


def test_final_policy_factory_uses_atomic_registry(tmp_path, monkeypatch) -> None:
    mcp_preflight.merge_preflights.cache_clear()
    mcp_preflight.merge_policies.cache_clear()
    mcp_preflight.workspace.cache_clear()
    monkeypatch.setenv("WEAVE_DB_PATH", str(tmp_path / "policy-factory.db"))

    registry = mcp_preflight.merge_policies()
    try:
        assert isinstance(registry, MergePolicyRegistry)
    finally:
        registry.workspace.close()
        mcp_preflight.merge_preflights.cache_clear()
        mcp_preflight.merge_policies.cache_clear()
        mcp_preflight.workspace.cache_clear()
