"""Regression coverage for the package-owned selected merge-train contract."""

from __future__ import annotations

import inspect

from weave_frontend import selected_merge_train_preview as root_train
from weave_frontend.merges import (
    MAX_SELECTED_MERGE_TRAIN_SOURCES,
    SELECTED_MERGE_TRAIN_FORMAT,
    SelectedMergeTrainPreviewService,
)


def test_selected_merge_train_public_boundary_preserves_root_contract() -> None:
    assert SELECTED_MERGE_TRAIN_FORMAT == root_train.SELECTED_MERGE_TRAIN_FORMAT
    assert (
        MAX_SELECTED_MERGE_TRAIN_SOURCES
        == root_train.MAX_SELECTED_MERGE_TRAIN_SOURCES
    )
    for method in ("__init__", "preview"):
        package_signature = inspect.signature(
            getattr(SelectedMergeTrainPreviewService, method)
        )
        root_signature = inspect.signature(
            getattr(root_train.SelectedMergeTrainPreviewService, method)
        )
        assert package_signature == root_signature
