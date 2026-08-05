"""Canonical exact branch-head catalogs for project merge orchestration."""

from __future__ import annotations

from typing import Any

from .errors import ValidationError
from .project_agent_status import MAX_AGENT_STATUS_BRANCH_CATALOG

PROJECT_MERGE_CATALOG_FORMAT = "weave-project-merge-queue-catalog-v1"


class ProjectMergeCatalogService:
    """Capture one deterministic target/source branch-head catalog."""

    def __init__(self, workspace: Any) -> None:
        self.workspace = workspace

    def capture(
        self,
        project: str,
        target_branch: str,
        *,
        invalid_target_code: str,
    ) -> dict[str, Any]:
        """Return the exact lexical project catalog for one target branch."""

        project_id = self.workspace.project_id(project)
        members = self.members(project_id)
        target = next(
            (member for member in members if member["branch"] == target_branch),
            None,
        )
        if target is None:
            raise ValidationError(
                invalid_target_code,
                f"target branch {target_branch!r} is not in the project catalog",
            )
        sources = [member for member in members if member["branch"] != target_branch]
        catalog_id = self.workspace.db.hash_value(
            {
                "format": PROJECT_MERGE_CATALOG_FORMAT,
                "project": project,
                "target": target,
                "sources": sources,
            }
        )
        return {
            "project": project,
            "target": target,
            "sources": sources,
            "catalog_id": catalog_id,
        }

    def members(self, project_id: str) -> list[dict[str, str]]:
        """Return bounded lexical branch heads for one project identifier."""

        rows = self.workspace.db.connection.execute(
            """SELECT name, head_revision_id
               FROM branches
               WHERE project_id = ?
               ORDER BY name
               LIMIT ?""",
            (project_id, MAX_AGENT_STATUS_BRANCH_CATALOG + 1),
        ).fetchall()
        if len(rows) > MAX_AGENT_STATUS_BRANCH_CATALOG:
            raise ValidationError(
                "MERGE_QUEUE_BRANCH_FANOUT_EXCEEDED",
                f"project merge queue supports at most {MAX_AGENT_STATUS_BRANCH_CATALOG} branches",
            )
        return [
            {
                "branch": str(row["name"]),
                "head_revision_id": str(row["head_revision_id"]),
            }
            for row in rows
        ]
