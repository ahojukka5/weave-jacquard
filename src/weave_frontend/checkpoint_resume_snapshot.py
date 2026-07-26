"""Resume snapshots extended with exact revision-bound agent checkpoints."""

from __future__ import annotations

from typing import Any

from .agent_checkpoint import AgentCheckpointRegistry
from .resume_snapshot import ResumeSnapshotService


class CheckpointResumeSnapshotService(ResumeSnapshotService):
    """Compose the base bounded snapshot plus its first-parent checkpoint view."""

    def __init__(
        self,
        workspace: Any,
        targets: Any,
        policies: Any,
        checkpoints: AgentCheckpointRegistry,
    ) -> None:
        super().__init__(workspace, targets, policies)
        self.checkpoints = checkpoints

    def snapshot(
        self,
        project: str,
        branch: str = "main",
        **kwargs: Any,
    ) -> dict[str, Any]:
        result = super().snapshot(project, branch, **kwargs)
        selected_revision_id = str(result["revision_id"])
        result.pop("snapshot_id")
        result["agent_checkpoint"] = self.checkpoints.get(
            project,
            branch,
            revision_id=selected_revision_id,
        )
        result["snapshot_id"] = self._snapshot_id(result)
        return result
