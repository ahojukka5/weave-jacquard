"""Regression coverage for the package-owned checkpoint timeline contract."""

from __future__ import annotations

import inspect

from weave_frontend import agent_checkpoint_timeline as root_timeline
from weave_frontend.resume import (
    CHECKPOINT_COMPARISON_FORMAT,
    CHECKPOINT_TIMELINE_FORMAT,
    AgentCheckpointTimelineService,
)


def test_checkpoint_timeline_public_boundary_preserves_root_contract() -> None:
    assert CHECKPOINT_TIMELINE_FORMAT == root_timeline.CHECKPOINT_TIMELINE_FORMAT
    assert CHECKPOINT_COMPARISON_FORMAT == root_timeline.CHECKPOINT_COMPARISON_FORMAT
    for method in ("page", "compare"):
        package_signature = inspect.signature(
            getattr(AgentCheckpointTimelineService, method)
        )
        root_signature = inspect.signature(
            getattr(root_timeline.AgentCheckpointTimelineService, method)
        )
        assert package_signature == root_signature
