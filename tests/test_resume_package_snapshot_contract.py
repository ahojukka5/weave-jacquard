"""Regression coverage for the package-owned base resume snapshot contract."""

from __future__ import annotations

import inspect

from weave_frontend import resume_snapshot as root_snapshot
from weave_frontend.resume import (
    MAX_RESUME_BRANCHES,
    MAX_RESUME_CONTEXTS,
    MAX_RESUME_DOCUMENTS,
    MAX_RESUME_HISTORY,
    MAX_RESUME_OPERATIONS,
    MAX_RESUME_TARGET_SOURCES,
    MAX_RESUME_TARGETS,
    RESUME_SNAPSHOT_FORMAT,
    ResumeSnapshotService,
)


def test_resume_snapshot_public_boundary_preserves_root_contract() -> None:
    assert RESUME_SNAPSHOT_FORMAT == root_snapshot.RESUME_SNAPSHOT_FORMAT
    for name, value in (
        ("MAX_RESUME_BRANCHES", MAX_RESUME_BRANCHES),
        ("MAX_RESUME_CONTEXTS", MAX_RESUME_CONTEXTS),
        ("MAX_RESUME_DOCUMENTS", MAX_RESUME_DOCUMENTS),
        ("MAX_RESUME_HISTORY", MAX_RESUME_HISTORY),
        ("MAX_RESUME_OPERATIONS", MAX_RESUME_OPERATIONS),
        ("MAX_RESUME_TARGET_SOURCES", MAX_RESUME_TARGET_SOURCES),
        ("MAX_RESUME_TARGETS", MAX_RESUME_TARGETS),
    ):
        assert value == getattr(root_snapshot, name)
    assert inspect.signature(ResumeSnapshotService.snapshot) == inspect.signature(
        root_snapshot.ResumeSnapshotService.snapshot
    )
