from __future__ import annotations

from pathlib import Path

import pytest

from weave_frontend import SExpressionWorkspace, ValidationError
from weave_frontend.merges import (
    PROJECT_MERGE_CATALOG_FORMAT,
    PROJECT_MERGE_QUEUE_CATALOG_FORMAT,
    MergePreviewService,
    ProjectMergeCatalogService,
    ProjectMergeQueueService,
    SelectedMergePreflightBatchService,
    SelectedMergeTrainPreviewService,
)
from weave_frontend.resume import AgentCheckpointRegistry, ProjectAgentStatusService
from weave_frontend.revision_limits import MAX_AGENT_STATUS_BRANCH_CATALOG


def test_project_merge_catalog_is_deterministic_and_protocol_compatible(
    tmp_path: Path,
) -> None:
    with SExpressionWorkspace(tmp_path / "catalog.db") as workspace:
        _, revision_id = workspace.initialize("demo")
        workspace.create_branch_at_revision("demo", "zeta", revision_id)
        workspace.create_branch_at_revision("demo", "alpha", revision_id)

        catalogs = ProjectMergeCatalogService(workspace)
        first = catalogs.capture(
            "demo",
            "main",
            invalid_target_code="INVALID_TEST_TARGET",
        )
        repeated = catalogs.capture(
            "demo",
            "main",
            invalid_target_code="INVALID_TEST_TARGET",
        )

        assert PROJECT_MERGE_CATALOG_FORMAT == PROJECT_MERGE_QUEUE_CATALOG_FORMAT
        assert first == repeated
        assert first["target"] == {
            "branch": "main",
            "head_revision_id": revision_id,
        }
        assert [source["branch"] for source in first["sources"]] == [
            "alpha",
            "zeta",
        ]
        assert first["catalog_id"] == workspace.db.hash_value(
            {
                "format": PROJECT_MERGE_QUEUE_CATALOG_FORMAT,
                "project": "demo",
                "target": first["target"],
                "sources": first["sources"],
            }
        )


def test_project_merge_catalog_preserves_caller_error_contract(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "invalid.db") as workspace:
        workspace.initialize("demo")
        catalogs = ProjectMergeCatalogService(workspace)

        with pytest.raises(ValidationError) as raised:
            catalogs.capture(
                "demo",
                "missing",
                invalid_target_code="INVALID_SELECTED_PREFLIGHT_TARGET",
            )

        assert raised.value.code == "INVALID_SELECTED_PREFLIGHT_TARGET"
        assert "missing" in str(raised.value)


def test_project_merge_consumers_share_one_catalog_service(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "shared.db") as workspace:
        _, revision_id = workspace.initialize("demo")
        workspace.create_branch_at_revision("demo", "source", revision_id)
        registry = AgentCheckpointRegistry(workspace)
        catalogs = ProjectMergeCatalogService(workspace)
        queue = ProjectMergeQueueService(
            MergePreviewService(workspace),
            ProjectAgentStatusService(registry),
            catalogs,
        )
        selected = SelectedMergePreflightBatchService(queue, object())  # type: ignore[arg-type]
        train = SelectedMergeTrainPreviewService(queue)

        assert queue.catalogs is catalogs
        assert selected.catalogs is catalogs
        assert train.catalogs is catalogs
        assert queue.page("demo", limit=1)["catalog_id"] == catalogs.capture(
            "demo",
            "main",
            invalid_target_code="INVALID_MERGE_QUEUE_TARGET",
        )["catalog_id"]


def test_project_merge_catalog_rejects_unbounded_fanout(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "fanout.db") as workspace:
        _, revision_id = workspace.initialize("demo")
        project_id = workspace.project_id("demo")
        workspace.db.connection.executemany(
            "INSERT INTO branches(name, project_id, head_revision_id) VALUES (?, ?, ?)",
            [
                (f"branch-{index:04d}", project_id, revision_id)
                for index in range(MAX_AGENT_STATUS_BRANCH_CATALOG)
            ],
        )
        workspace.db.connection.commit()

        with pytest.raises(ValidationError) as raised:
            ProjectMergeCatalogService(workspace).capture(
                "demo",
                "main",
                invalid_target_code="INVALID_MERGE_QUEUE_TARGET",
            )

        assert raised.value.code == "MERGE_QUEUE_BRANCH_FANOUT_EXCEEDED"
