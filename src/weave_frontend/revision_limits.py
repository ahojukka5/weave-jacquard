"""Central resource ceilings for revision-wide and history-wide operations."""

from __future__ import annotations

from typing import Any

from .errors import ValidationError
from .snapshot_codec import (
    MAX_QUALIFIED_NAME_BYTES,
    MAX_REVISION_DECODED_BYTES,
    MAX_REVISION_MODULES,
    MAX_SNAPSHOT_COMPRESSED_BYTES,
    MAX_SNAPSHOT_DECOMPRESSED_BYTES,
)

MAX_BUILD_DOCUMENTS = 256
MAX_REVISION_DAG_NODES = 65_536
MAX_REVISION_DAG_EDGES = 131_072
MAX_BRANCH_HISTORY_PAGE_SIZE = 200
MAX_BRANCH_ACTIVITY_REVISIONS = 65_536
MAX_OPERATION_PAGE_SIZE = 200
MAX_NODE_FIND_RESULTS = 500
MAX_NODE_INSPECT_DEPTH = 64
MAX_REVISION_DIFF_PAGE_SIZE = 200
MAX_MERGE_TARGET_IMPACT_PAGE_SIZE = 200
MAX_CHECKPOINT_TIMELINE_PAGE = 50
MAX_CHECKPOINT_REVISION_SCAN = 500
MAX_AGENT_STATUS_PAGE = 100
MAX_AGENT_STATUS_BRANCH_CATALOG = 1_000
MAX_AGENT_STATUS_CHECKPOINT_SCAN = 500
MAX_PROJECT_MERGE_QUEUE_PAGE = 20
MAX_PROJECT_MERGE_QUEUE_CONFLICTS = 100
MAX_PROJECT_MERGE_QUEUE_DOCUMENTS = 200
MAX_PROJECT_MERGE_IMPACT_QUEUE_PAGE = 10
MAX_PROJECT_MERGE_IMPACT_QUEUE_DOCUMENTS = 200
MAX_SELECTED_MERGE_TRAIN_SOURCES = 10
MAX_SELECTED_MERGE_PREFLIGHT_SOURCES = 5
MAX_SELECTED_MERGE_PREFLIGHT_DOCUMENTS = 200
MAX_RESUME_DOCUMENTS = 200
MAX_RESUME_TARGETS = 100
MAX_RESUME_TARGET_SOURCES = 200
MAX_RESUME_CONTEXTS = 100
MAX_RESUME_BRANCHES = 200
MAX_RESUME_HISTORY = 50
MAX_RESUME_OPERATIONS = 200
MAX_RESUME_TEST_TARGETS = 100
MAX_RESUME_TASKS = 100
MAX_AFFECTED_TARGET_VALIDATIONS = 64
MAX_PREFLIGHT_IMPACT_TARGETS = 200

REVISION_RESOURCE_LIMITS: dict[str, int] = {
    "affected_target_validations": MAX_AFFECTED_TARGET_VALIDATIONS,
    "agent_status_branch_catalog": MAX_AGENT_STATUS_BRANCH_CATALOG,
    "agent_status_checkpoint_scan": MAX_AGENT_STATUS_CHECKPOINT_SCAN,
    "agent_status_page": MAX_AGENT_STATUS_PAGE,
    "branch_activity_revisions": MAX_BRANCH_ACTIVITY_REVISIONS,
    "branch_history_page_size": MAX_BRANCH_HISTORY_PAGE_SIZE,
    "build_documents": MAX_BUILD_DOCUMENTS,
    "checkpoint_revision_scan": MAX_CHECKPOINT_REVISION_SCAN,
    "checkpoint_timeline_page": MAX_CHECKPOINT_TIMELINE_PAGE,
    "merge_target_impact_page_size": MAX_MERGE_TARGET_IMPACT_PAGE_SIZE,
    "node_find_results": MAX_NODE_FIND_RESULTS,
    "node_inspect_depth": MAX_NODE_INSPECT_DEPTH,
    "operation_page_size": MAX_OPERATION_PAGE_SIZE,
    "preflight_impact_targets": MAX_PREFLIGHT_IMPACT_TARGETS,
    "project_merge_impact_queue_documents": (
        MAX_PROJECT_MERGE_IMPACT_QUEUE_DOCUMENTS
    ),
    "project_merge_impact_queue_page": MAX_PROJECT_MERGE_IMPACT_QUEUE_PAGE,
    "project_merge_queue_conflicts": MAX_PROJECT_MERGE_QUEUE_CONFLICTS,
    "project_merge_queue_documents": MAX_PROJECT_MERGE_QUEUE_DOCUMENTS,
    "project_merge_queue_page": MAX_PROJECT_MERGE_QUEUE_PAGE,
    "qualified_name_bytes": MAX_QUALIFIED_NAME_BYTES,
    "resume_branches": MAX_RESUME_BRANCHES,
    "resume_contexts": MAX_RESUME_CONTEXTS,
    "resume_documents": MAX_RESUME_DOCUMENTS,
    "resume_history": MAX_RESUME_HISTORY,
    "resume_operations": MAX_RESUME_OPERATIONS,
    "resume_target_sources": MAX_RESUME_TARGET_SOURCES,
    "resume_targets": MAX_RESUME_TARGETS,
    "resume_tasks": MAX_RESUME_TASKS,
    "resume_test_targets": MAX_RESUME_TEST_TARGETS,
    "revision_dag_edges": MAX_REVISION_DAG_EDGES,
    "revision_dag_nodes": MAX_REVISION_DAG_NODES,
    "revision_decoded_bytes": MAX_REVISION_DECODED_BYTES,
    "revision_diff_page_size": MAX_REVISION_DIFF_PAGE_SIZE,
    "revision_modules": MAX_REVISION_MODULES,
    "selected_merge_preflight_documents": MAX_SELECTED_MERGE_PREFLIGHT_DOCUMENTS,
    "selected_merge_preflight_sources": MAX_SELECTED_MERGE_PREFLIGHT_SOURCES,
    "selected_merge_train_sources": MAX_SELECTED_MERGE_TRAIN_SOURCES,
    "snapshot_compressed_bytes": MAX_SNAPSHOT_COMPRESSED_BYTES,
    "snapshot_decompressed_bytes": MAX_SNAPSHOT_DECOMPRESSED_BYTES,
}


def require_bounded_int(
    value: Any,
    *,
    code: str,
    name: str,
    minimum: int,
    maximum: int,
) -> int:
    """Return one integer in an explicit closed interval or fail predictably."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(code, f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise ValidationError(
            code,
            f"{name} must be between {minimum} and {maximum}",
        )
    return value


def require_nonnegative_int(value: Any, *, code: str, name: str) -> int:
    """Return one non-negative integer while rejecting booleans explicitly."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValidationError(code, f"{name} must be a non-negative integer")
    return value


__all__ = [
    "MAX_AFFECTED_TARGET_VALIDATIONS",
    "MAX_AGENT_STATUS_BRANCH_CATALOG",
    "MAX_AGENT_STATUS_CHECKPOINT_SCAN",
    "MAX_AGENT_STATUS_PAGE",
    "MAX_BRANCH_ACTIVITY_REVISIONS",
    "MAX_BRANCH_HISTORY_PAGE_SIZE",
    "MAX_BUILD_DOCUMENTS",
    "MAX_CHECKPOINT_REVISION_SCAN",
    "MAX_CHECKPOINT_TIMELINE_PAGE",
    "MAX_MERGE_TARGET_IMPACT_PAGE_SIZE",
    "MAX_NODE_FIND_RESULTS",
    "MAX_NODE_INSPECT_DEPTH",
    "MAX_OPERATION_PAGE_SIZE",
    "MAX_PREFLIGHT_IMPACT_TARGETS",
    "MAX_PROJECT_MERGE_IMPACT_QUEUE_DOCUMENTS",
    "MAX_PROJECT_MERGE_IMPACT_QUEUE_PAGE",
    "MAX_PROJECT_MERGE_QUEUE_CONFLICTS",
    "MAX_PROJECT_MERGE_QUEUE_DOCUMENTS",
    "MAX_PROJECT_MERGE_QUEUE_PAGE",
    "MAX_QUALIFIED_NAME_BYTES",
    "MAX_RESUME_BRANCHES",
    "MAX_RESUME_CONTEXTS",
    "MAX_RESUME_DOCUMENTS",
    "MAX_RESUME_HISTORY",
    "MAX_RESUME_OPERATIONS",
    "MAX_RESUME_TARGET_SOURCES",
    "MAX_RESUME_TARGETS",
    "MAX_RESUME_TASKS",
    "MAX_RESUME_TEST_TARGETS",
    "MAX_REVISION_DAG_EDGES",
    "MAX_REVISION_DAG_NODES",
    "MAX_REVISION_DECODED_BYTES",
    "MAX_REVISION_DIFF_PAGE_SIZE",
    "MAX_REVISION_MODULES",
    "MAX_SELECTED_MERGE_PREFLIGHT_DOCUMENTS",
    "MAX_SELECTED_MERGE_PREFLIGHT_SOURCES",
    "MAX_SELECTED_MERGE_TRAIN_SOURCES",
    "MAX_SNAPSHOT_COMPRESSED_BYTES",
    "MAX_SNAPSHOT_DECOMPRESSED_BYTES",
    "REVISION_RESOURCE_LIMITS",
    "require_bounded_int",
    "require_nonnegative_int",
]
