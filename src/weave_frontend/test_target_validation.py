"""Cross-document integrity checks for revisioned behavioral test metadata."""

from __future__ import annotations

from typing import Any

from .errors import ValidationError
from .project_metadata import TEST_TARGET_PREFIX
from .sexpr import JsonObject
from .test_targets import TestTargetRegistry


def test_target_references(
    state: dict[str, JsonObject],
) -> dict[str, list[str]]:
    """Return build-target names to lexical test names from one exact state."""

    references: dict[str, list[str]] = {}
    for storage_document, root in sorted(state.items()):
        if not storage_document.startswith(TEST_TARGET_PREFIX):
            continue
        name = storage_document[len(TEST_TARGET_PREFIX) :]
        config = TestTargetRegistry._parse_tree(root, name=name)
        references.setdefault(str(config["build_target"]), []).append(name)
    return references


def validate_test_target_references(state: dict[str, JsonObject]) -> None:
    """Reject any exact state containing a dangling behavioral test binding."""

    for build_target, test_names in test_target_references(state).items():
        try:
            TestTargetRegistry._require_build_target(state, build_target)
        except Exception as exc:
            raise ValidationError(
                "INVALID_TEST_TARGET_REFERENCE",
                f"build target {build_target!r} is required by tests {test_names!r}",
            ) from exc


def require_build_target_not_referenced(
    state: dict[str, JsonObject],
    build_target: str,
) -> None:
    """Reject deletion of a build target still used by revisioned tests."""

    test_names = test_target_references(state).get(build_target, [])
    if test_names:
        raise ValidationError(
            "BUILD_TARGET_IN_USE",
            f"build target {build_target!r} is required by tests {test_names!r}",
        )
