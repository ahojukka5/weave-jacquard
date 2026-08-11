"""Regression coverage for metadata-aware selected merge simulation ownership."""

from __future__ import annotations

import inspect

from weave_frontend import metadata_selected_merge_train_preview as root_metadata
from weave_frontend.merges import (
    MetadataSelectedMergeTrainPreviewService,
    SelectedMergeTrainPreviewService,
)


def test_metadata_selected_merge_service_preserves_extension_contract() -> None:
    assert issubclass(
        MetadataSelectedMergeTrainPreviewService,
        SelectedMergeTrainPreviewService,
    )
    assert inspect.signature(
        MetadataSelectedMergeTrainPreviewService._step
    ) == inspect.signature(root_metadata.SelectedMergeTrainPreviewService._step)
