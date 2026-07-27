"""Shared classification for revisioned non-source project metadata."""

from __future__ import annotations

BUILD_TARGET_PREFIX = "@build-target/"
TEST_TARGET_PREFIX = "@test-target/"
TASK_CONTRACT_PREFIX = "@task/"

RESERVED_PROJECT_METADATA_PREFIXES = (
    BUILD_TARGET_PREFIX,
    TEST_TARGET_PREFIX,
    TASK_CONTRACT_PREFIX,
)


def is_project_metadata_document(document: str) -> bool:
    """Return whether a module snapshot is reserved non-source metadata."""

    return document.startswith(RESERVED_PROJECT_METADATA_PREFIXES)


def metadata_kind(document: str) -> str | None:
    """Return the stable metadata class for a reserved document name."""

    if document.startswith(BUILD_TARGET_PREFIX):
        return "build_target"
    if document.startswith(TEST_TARGET_PREFIX):
        return "test_target"
    if document.startswith(TASK_CONTRACT_PREFIX):
        return "task_contract"
    return None
