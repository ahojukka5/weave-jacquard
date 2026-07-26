from __future__ import annotations

from typing import Any

from weave_frontend import mcp_concurrent_branches
from weave_frontend.errors import ValidationError


class _Workspace:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def create_branch(self, *args: Any, **kwargs: Any) -> str:
        self.calls.append(("create_branch", args, kwargs))
        return str(kwargs["expected_revision_id"] or "revision-current")

    def create_branch_at_revision(self, *args: Any, **kwargs: Any) -> str:
        self.calls.append(("create_branch_at_revision", args, kwargs))
        return str(args[2])


def test_branch_create_forwards_expected_source_head(monkeypatch) -> None:
    workspace = _Workspace()
    monkeypatch.setattr(mcp_concurrent_branches, "workspace", lambda: workspace)

    response = mcp_concurrent_branches.branch_create(
        "demo",
        "feature",
        from_branch="develop",
        expected_revision_id="revision-base",
    )

    assert response == {"ok": True, "result": "revision-base"}
    assert workspace.calls == [
        (
            "create_branch",
            ("demo", "feature"),
            {
                "from_branch": "develop",
                "expected_revision_id": "revision-base",
            },
        )
    ]


def test_exact_revision_branch_tool_forwards_revision(monkeypatch) -> None:
    workspace = _Workspace()
    monkeypatch.setattr(mcp_concurrent_branches, "workspace", lambda: workspace)

    response = mcp_concurrent_branches.branch_create_at_revision(
        "demo",
        "historical",
        "revision-old",
    )

    assert response == {"ok": True, "result": "revision-old"}
    assert workspace.calls == [
        (
            "create_branch_at_revision",
            ("demo", "historical", "revision-old"),
            {},
        )
    ]


def test_branch_create_returns_structured_stale_error(monkeypatch) -> None:
    class _Stale:
        def create_branch(self, *args: Any, **kwargs: Any) -> str:
            raise ValidationError("STALE_BRANCH_HEAD", "source branch advanced")

    monkeypatch.setattr(mcp_concurrent_branches, "workspace", lambda: _Stale())

    response = mcp_concurrent_branches.branch_create(
        "demo",
        "feature",
        expected_revision_id="revision-old",
    )

    assert response["ok"] is False
    assert response["error"] == {
        "code": "STALE_BRANCH_HEAD",
        "message": "source branch advanced",
        "node_id": None,
    }


def test_exact_revision_branch_returns_duplicate_error(monkeypatch) -> None:
    class _Duplicate:
        def create_branch_at_revision(self, *args: Any, **kwargs: Any) -> str:
            raise ValidationError("DUPLICATE_BRANCH", "branch exists")

    monkeypatch.setattr(mcp_concurrent_branches, "workspace", lambda: _Duplicate())

    response = mcp_concurrent_branches.branch_create_at_revision(
        "demo",
        "feature",
        "revision-old",
    )

    assert response["ok"] is False
    assert response["error"]["code"] == "DUPLICATE_BRANCH"
