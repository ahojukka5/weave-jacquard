"""Merge-train simulation extended with test-target reference integrity."""

from __future__ import annotations

from typing import Any

from .selected_merge_train_preview import SelectedMergeTrainPreviewService as _Base
from .test_target_validation import validate_test_target_references


class SelectedMergeTrainPreviewService(_Base):
    """Reject virtual train steps that create dangling behavioral tests."""

    def _step(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        result = super()._step(*args, **kwargs)
        merged_state = result.get("merged_state")
        if isinstance(merged_state, dict):
            validate_test_target_references(merged_state)
        return result
