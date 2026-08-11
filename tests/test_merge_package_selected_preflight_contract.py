"""Regression coverage for the package-owned selected preflight batch contract."""

from __future__ import annotations

import inspect

from weave_frontend import selected_merge_preflight_batch as root_batch
from weave_frontend.merges import (
    MAX_SELECTED_MERGE_PREFLIGHT_DOCUMENTS,
    MAX_SELECTED_MERGE_PREFLIGHT_SOURCES,
    SELECTED_MERGE_PREFLIGHT_BATCH_FORMAT,
    SelectedMergePreflightBatchService,
)


def test_selected_preflight_public_boundary_preserves_root_contract() -> None:
    assert (
        SELECTED_MERGE_PREFLIGHT_BATCH_FORMAT
        == root_batch.SELECTED_MERGE_PREFLIGHT_BATCH_FORMAT
    )
    assert (
        MAX_SELECTED_MERGE_PREFLIGHT_SOURCES
        == root_batch.MAX_SELECTED_MERGE_PREFLIGHT_SOURCES
    )
    assert (
        MAX_SELECTED_MERGE_PREFLIGHT_DOCUMENTS
        == root_batch.MAX_SELECTED_MERGE_PREFLIGHT_DOCUMENTS
    )
    for method in ("__init__", "run"):
        package_signature = inspect.signature(
            getattr(SelectedMergePreflightBatchService, method)
        )
        root_signature = inspect.signature(
            getattr(root_batch.SelectedMergePreflightBatchService, method)
        )
        assert package_signature == root_signature
