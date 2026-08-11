"""Regression coverage for the package-owned project agent-status contract."""

from __future__ import annotations

import inspect

from weave_frontend import project_agent_status as root_status
from weave_frontend.resume import (
    MAX_AGENT_STATUS_BRANCH_CATALOG,
    MAX_AGENT_STATUS_CHECKPOINT_SCAN,
    MAX_AGENT_STATUS_PAGE,
    PROJECT_AGENT_STATUS_CATALOG_FORMAT,
    PROJECT_AGENT_STATUS_FORMAT,
    ProjectAgentStatusService,
)


def test_project_status_public_boundary_preserves_root_contract() -> None:
    assert PROJECT_AGENT_STATUS_FORMAT == root_status.PROJECT_AGENT_STATUS_FORMAT
    assert (
        PROJECT_AGENT_STATUS_CATALOG_FORMAT
        == root_status.PROJECT_AGENT_STATUS_CATALOG_FORMAT
    )
    assert MAX_AGENT_STATUS_PAGE == root_status.MAX_AGENT_STATUS_PAGE
    assert (
        MAX_AGENT_STATUS_BRANCH_CATALOG == root_status.MAX_AGENT_STATUS_BRANCH_CATALOG
    )
    assert (
        MAX_AGENT_STATUS_CHECKPOINT_SCAN == root_status.MAX_AGENT_STATUS_CHECKPOINT_SCAN
    )
    assert inspect.signature(ProjectAgentStatusService.page) == inspect.signature(
        root_status.ProjectAgentStatusService.page
    )
