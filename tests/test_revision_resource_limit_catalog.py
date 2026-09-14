"""Catalog drift and import-direction coverage for revision resource limits.

#257 test-value audit of this file:

Keep equality only where a domain publishes an independently defined
compatibility constant that can drift from `revision_limits` without a
behavior test noticing. Those tests catch silent catalog/service split.

Do not equality-test package re-exports that import the catalog names.
That only proves Python aliasing. Those modules are guarded by
import-direction assertions instead.

Acceptance/rejection of max, over-limit, and invalid inputs remains in
`test_public_revision_resource_limits.py` and the domain behavior suites.
"""

from __future__ import annotations

import ast
from pathlib import Path

from weave_frontend import revision_limits
from weave_frontend.agent_checkpoint_timeline import (
    MAX_CHECKPOINT_PAGE,
    MAX_CHECKPOINT_REVISION_SCAN,
)
from weave_frontend.merge_validation_set import MAX_AFFECTED_TARGET_VALIDATIONS
from weave_frontend.project_agent_status import (
    MAX_AGENT_STATUS_BRANCH_CATALOG,
    MAX_AGENT_STATUS_CHECKPOINT_SCAN,
    MAX_AGENT_STATUS_PAGE,
)
from weave_frontend.resume_snapshot import (
    MAX_RESUME_BRANCHES,
    MAX_RESUME_CONTEXTS,
    MAX_RESUME_DOCUMENTS,
    MAX_RESUME_HISTORY,
    MAX_RESUME_OPERATIONS,
    MAX_RESUME_TARGET_SOURCES,
    MAX_RESUME_TARGETS,
)
from weave_frontend.selected_merge_preflight_batch import (
    MAX_SELECTED_MERGE_PREFLIGHT_DOCUMENTS,
    MAX_SELECTED_MERGE_PREFLIGHT_SOURCES,
)
from weave_frontend.selected_merge_train_preview import (
    MAX_SELECTED_MERGE_TRAIN_SOURCES,
)
from weave_frontend.task_resume_snapshot import MAX_RESUME_TASKS
from weave_frontend.test_resume_snapshot import MAX_RESUME_TEST_TARGETS

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "src" / "weave_frontend"


def _imported_from_revision_limits(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module != "revision_limits" and not (
            node.module or ""
        ).endswith("revision_limits"):
            continue
        for alias in node.names:
            names.add(alias.name)
    return names


def _assigned_integer_constants(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not (
            isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, int)
        ):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def test_checkpoint_and_agent_status_limits_match_the_central_catalog() -> None:
    """Independent public page/scan ceilings vs catalog names.

    Failure class: a timeline or agent-status module keeps its own literal
    after `revision_limits` changes, so published page and scan bounds
    silently disagree with the documented catalog.
    """

    assert MAX_CHECKPOINT_PAGE == revision_limits.MAX_CHECKPOINT_TIMELINE_PAGE
    assert (
        MAX_CHECKPOINT_REVISION_SCAN
        == revision_limits.MAX_CHECKPOINT_REVISION_SCAN
    )
    assert MAX_AGENT_STATUS_PAGE == revision_limits.MAX_AGENT_STATUS_PAGE
    assert (
        MAX_AGENT_STATUS_BRANCH_CATALOG
        == revision_limits.MAX_AGENT_STATUS_BRANCH_CATALOG
    )
    assert (
        MAX_AGENT_STATUS_CHECKPOINT_SCAN
        == revision_limits.MAX_AGENT_STATUS_CHECKPOINT_SCAN
    )


def test_resume_limits_match_the_central_catalog() -> None:
    """Independent resume snapshot fanout ceilings vs catalog names.

    Failure class: resume, test-resume, or task-resume modules keep their
    own literals after the catalog changes, so orientation pages admit a
    different bound than `REVISION_RESOURCE_LIMITS`.
    """

    assert MAX_RESUME_DOCUMENTS == revision_limits.MAX_RESUME_DOCUMENTS
    assert MAX_RESUME_TARGETS == revision_limits.MAX_RESUME_TARGETS
    assert MAX_RESUME_TARGET_SOURCES == revision_limits.MAX_RESUME_TARGET_SOURCES
    assert MAX_RESUME_CONTEXTS == revision_limits.MAX_RESUME_CONTEXTS
    assert MAX_RESUME_BRANCHES == revision_limits.MAX_RESUME_BRANCHES
    assert MAX_RESUME_HISTORY == revision_limits.MAX_RESUME_HISTORY
    assert MAX_RESUME_OPERATIONS == revision_limits.MAX_RESUME_OPERATIONS
    assert MAX_RESUME_TEST_TARGETS == revision_limits.MAX_RESUME_TEST_TARGETS
    assert MAX_RESUME_TASKS == revision_limits.MAX_RESUME_TASKS


def test_queue_and_preflight_limits_match_the_central_catalog() -> None:
    """Independent merge-service compatibility ceilings vs catalog names.

    Failure class: root validation-set, selected-train, or selected-preflight
    modules keep their own literals after the catalog changes. Package
    modules that import the catalog are not equality-tested here.
    """

    assert (
        MAX_AFFECTED_TARGET_VALIDATIONS
        == revision_limits.MAX_AFFECTED_TARGET_VALIDATIONS
    )
    assert (
        MAX_SELECTED_MERGE_TRAIN_SOURCES
        == revision_limits.MAX_SELECTED_MERGE_TRAIN_SOURCES
    )
    assert (
        MAX_SELECTED_MERGE_PREFLIGHT_SOURCES
        == revision_limits.MAX_SELECTED_MERGE_PREFLIGHT_SOURCES
    )
    assert (
        MAX_SELECTED_MERGE_PREFLIGHT_DOCUMENTS
        == revision_limits.MAX_SELECTED_MERGE_PREFLIGHT_DOCUMENTS
    )


def test_selected_merge_package_sources_limits_from_the_central_catalog() -> None:
    """Package selected-train/preflight must import catalog names.

    Failure class: a package implementation reintroduces a local integer
    literal, so its bound can drift from `revision_limits` while still
    matching a tautological `imported_name == catalog_name` assertion.
    """

    train = FRONTEND / "merges" / "selected_train.py"
    preflight = FRONTEND / "merges" / "selected_preflight.py"
    train_imported = _imported_from_revision_limits(train)
    preflight_imported = _imported_from_revision_limits(preflight)
    train_literals = _assigned_integer_constants(train)
    preflight_literals = _assigned_integer_constants(preflight)

    assert "MAX_SELECTED_MERGE_TRAIN_SOURCES" in train_imported
    assert "MAX_SELECTED_MERGE_TRAIN_SOURCES" not in train_literals
    assert "MAX_SELECTED_MERGE_PREFLIGHT_SOURCES" in preflight_imported
    assert "MAX_SELECTED_MERGE_PREFLIGHT_DOCUMENTS" in preflight_imported
    assert "MAX_AFFECTED_TARGET_VALIDATIONS" in preflight_imported
    assert "MAX_SELECTED_MERGE_PREFLIGHT_SOURCES" not in preflight_literals
    assert "MAX_SELECTED_MERGE_PREFLIGHT_DOCUMENTS" not in preflight_literals
    assert "MAX_AFFECTED_TARGET_VALIDATIONS" not in preflight_literals
