from __future__ import annotations

from typing import Any

from weave_frontend import mcp_resume_snapshot
from weave_frontend.resume_snapshot import ResumeSnapshotService


class _Snapshots:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def snapshot(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((args, kwargs))
        return {
            "format": "weave-agent-resume-snapshot-v1",
            "revision_id": kwargs["revision_id"],
            "snapshot_id": "snapshot-1",
        }


def test_resume_snapshot_tool_forwards_revision_and_bounds(monkeypatch) -> None:
    snapshots = _Snapshots()
    monkeypatch.setattr(mcp_resume_snapshot, "resume_snapshots", lambda: snapshots)

    response = mcp_resume_snapshot.branch_resume_snapshot(
        "demo",
        "feature",
        revision_id="revision-old",
        document_limit=20,
        target_limit=10,
        target_source_limit=9,
        test_target_limit=4,
        task_limit=3,
        context_limit=8,
        branch_limit=7,
        history_limit=6,
        operation_limit=5,
    )

    assert response["ok"] is True
    assert response["result"]["snapshot_id"] == "snapshot-1"
    assert snapshots.calls == [
        (
            ("demo", "feature"),
            {
                "revision_id": "revision-old",
                "document_limit": 20,
                "target_limit": 10,
                "target_source_limit": 9,
                "test_target_limit": 4,
                "task_limit": 3,
                "context_limit": 8,
                "branch_limit": 7,
                "history_limit": 6,
                "operation_limit": 5,
            },
        )
    ]


def test_resume_snapshot_factory_composes_shared_services(tmp_path, monkeypatch) -> None:
    mcp_resume_snapshot.resume_snapshots.cache_clear()
    mcp_resume_snapshot.workspace.cache_clear()
    mcp_resume_snapshot.build_targets.cache_clear()
    mcp_resume_snapshot.merge_policies.cache_clear()
    mcp_resume_snapshot.test_targets.cache_clear()
    mcp_resume_snapshot.task_contracts.cache_clear()
    monkeypatch.setenv("WEAVE_DB_PATH", str(tmp_path / "resume-factory.db"))

    service = mcp_resume_snapshot.resume_snapshots()
    try:
        assert isinstance(service, ResumeSnapshotService)
        assert service.workspace is mcp_resume_snapshot.workspace()
        assert service.targets is mcp_resume_snapshot.build_targets()
        assert service.policies is mcp_resume_snapshot.merge_policies()
        assert service.tests is mcp_resume_snapshot.test_targets()
        assert service.tasks is mcp_resume_snapshot.task_contracts()
    finally:
        service.workspace.close()
        mcp_resume_snapshot.resume_snapshots.cache_clear()
        mcp_resume_snapshot.build_targets.cache_clear()
        mcp_resume_snapshot.merge_policies.cache_clear()
        mcp_resume_snapshot.test_targets.cache_clear()
        mcp_resume_snapshot.task_contracts.cache_clear()
        mcp_resume_snapshot.workspace.cache_clear()
