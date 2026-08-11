"""Regression coverage for the package-owned merge candidate build contract."""

from __future__ import annotations

import inspect

from weave_frontend import merge_candidate_build as root_candidate_build
from weave_frontend.merges import (
    MERGE_CANDIDATE_BUILD_FORMAT,
    MERGE_CANDIDATE_BUILD_KEY_FORMAT,
    MERGE_CANDIDATE_NODE_MAP_FORMAT,
    MergeCandidateBuildService,
)


def test_candidate_build_public_boundary_preserves_root_contract() -> None:
    assert (
        MERGE_CANDIDATE_BUILD_FORMAT
        == root_candidate_build.MERGE_CANDIDATE_BUILD_FORMAT
    )
    assert (
        MERGE_CANDIDATE_BUILD_KEY_FORMAT
        == root_candidate_build.MERGE_CANDIDATE_BUILD_KEY_FORMAT
    )
    assert (
        MERGE_CANDIDATE_NODE_MAP_FORMAT
        == root_candidate_build.MERGE_CANDIDATE_NODE_MAP_FORMAT
    )
    for method in ("build", "build_exact", "get"):
        package_signature = inspect.signature(
            getattr(MergeCandidateBuildService, method)
        )
        root_signature = inspect.signature(
            getattr(root_candidate_build.MergeCandidateBuildService, method)
        )
        assert package_signature == root_signature
