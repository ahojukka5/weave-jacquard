from __future__ import annotations

from typing import Any

from weave_frontend import mcp_revision_reads
from weave_frontend.errors import ValidationError


class _HistoryWorkspace:
    def history_page(
        self,
        project: str,
        branch: str,
        *,
        limit: int,
    ) -> dict[str, Any]:
        if limit > 200:
            raise ValidationError(
                "INVALID_BRANCH_HISTORY_LIMIT",
                "limit must be between 1 and 200",
            )
        return {
            "project": project,
            "branch": branch,
            "head_revision_id": "head",
            "limit": limit,
            "returned_count": 1,
            "truncated": True,
            "next_revision_id": "parent",
            "revisions": [{"id": "head"}],
            "limits": {"page_size": 200},
        }


def test_mcp_branch_history_exposes_truncation_metadata(monkeypatch) -> None:
    monkeypatch.setattr(mcp_revision_reads, "workspace", lambda: _HistoryWorkspace())

    response = mcp_revision_reads.branch_history("demo", "main", limit=1)

    assert response["ok"] is True
    assert response["result"]["revisions"] == [{"id": "head"}]
    assert response["result"]["returned_count"] == 1
    assert response["result"]["truncated"] is True
    assert response["result"]["next_revision_id"] == "parent"
    assert response["result"]["limits"] == {"page_size": 200}


def test_mcp_branch_history_preserves_limit_errors(monkeypatch) -> None:
    monkeypatch.setattr(mcp_revision_reads, "workspace", lambda: _HistoryWorkspace())

    response = mcp_revision_reads.branch_history("demo", limit=201)

    assert response["ok"] is False
    assert response["error"]["code"] == "INVALID_BRANCH_HISTORY_LIMIT"
