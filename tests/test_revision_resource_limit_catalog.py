from __future__ import annotations

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


def test_checkpoint_and_agent_status_limits_match_the_central_catalog() -> None:
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
