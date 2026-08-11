"""Regression coverage for the package-owned agent checkpoint contract."""

from __future__ import annotations

import inspect

from weave_frontend import agent_checkpoint as root_checkpoint
from weave_frontend.resume import (
    AGENT_CHECKPOINT_FORMAT,
    AGENT_CHECKPOINT_OPERATION,
    AGENT_CHECKPOINT_STATUSES,
    AGENT_CHECKPOINT_TITLE,
    AgentCheckpointRegistry,
)


def test_checkpoint_public_boundary_preserves_root_contract() -> None:
    assert AGENT_CHECKPOINT_FORMAT == root_checkpoint.AGENT_CHECKPOINT_FORMAT
    assert AGENT_CHECKPOINT_OPERATION == root_checkpoint.AGENT_CHECKPOINT_OPERATION
    assert AGENT_CHECKPOINT_STATUSES == root_checkpoint.AGENT_CHECKPOINT_STATUSES
    assert AGENT_CHECKPOINT_TITLE == root_checkpoint.AGENT_CHECKPOINT_TITLE
    for method in ("create", "get"):
        package_signature = inspect.signature(getattr(AgentCheckpointRegistry, method))
        root_signature = inspect.signature(
            getattr(root_checkpoint.AgentCheckpointRegistry, method)
        )
        assert package_signature == root_signature
