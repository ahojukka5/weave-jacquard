"""Regression coverage for the package-owned project merge queue contract."""

from __future__ import annotations

import inspect

from weave_frontend import project_merge_queue as root_queue
from weave_frontend.merges import (
    PROJECT_MERGE_QUEUE_CATALOG_FORMAT,
    PROJECT_MERGE_QUEUE_FORMAT,
    ProjectMergeQueueService,
)


def test_project_merge_queue_public_boundary_preserves_root_contract() -> None:
    assert PROJECT_MERGE_QUEUE_FORMAT == root_queue.PROJECT_MERGE_QUEUE_FORMAT
    assert (
        PROJECT_MERGE_QUEUE_CATALOG_FORMAT
        == root_queue.PROJECT_MERGE_QUEUE_CATALOG_FORMAT
    )
    for method in ("__init__", "page"):
        package_signature = inspect.signature(getattr(ProjectMergeQueueService, method))
        root_signature = inspect.signature(
            getattr(root_queue.ProjectMergeQueueService, method)
        )
        assert package_signature == root_signature
