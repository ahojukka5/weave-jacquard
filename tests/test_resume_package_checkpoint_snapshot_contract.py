"""Regression coverage for the package-owned checkpoint resume snapshot contract."""

from __future__ import annotations

import inspect

from weave_frontend import checkpoint_resume_snapshot as root_snapshot
from weave_frontend.resume import CheckpointResumeSnapshotService


def test_checkpoint_resume_snapshot_public_boundary_preserves_root_contract() -> None:
    assert inspect.signature(CheckpointResumeSnapshotService.__init__) == inspect.signature(
        root_snapshot.CheckpointResumeSnapshotService.__init__
    )
    assert inspect.signature(CheckpointResumeSnapshotService.snapshot) == inspect.signature(
        root_snapshot.CheckpointResumeSnapshotService.snapshot
    )
