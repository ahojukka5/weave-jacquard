"""Regression coverage for the package-owned project merge-impact queue contract."""

from __future__ import annotations

import inspect

from weave_frontend import project_merge_impact_queue as root_queue
from weave_frontend.merges import (
    PROJECT_MERGE_IMPACT_QUEUE_FORMAT,
    ProjectMergeImpactQueueService,
)


def test_project_merge_impact_queue_public_boundary_preserves_root_contract() -> None:
    assert (
        PROJECT_MERGE_IMPACT_QUEUE_FORMAT
        == root_queue.PROJECT_MERGE_IMPACT_QUEUE_FORMAT
    )
    for method in ("__init__", "page"):
        package_signature = inspect.signature(
            getattr(ProjectMergeImpactQueueService, method)
        )
        root_signature = inspect.signature(
            getattr(root_queue.ProjectMergeImpactQueueService, method)
        )
        assert package_signature == root_signature
