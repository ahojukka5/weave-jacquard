from __future__ import annotations

from pathlib import Path

from weave_frontend import SExpressionWorkspace
from weave_frontend.merges import MergePreviewService
from weave_frontend.revision_limits import (
    MAX_REVISION_DAG_EDGES,
    MAX_REVISION_DAG_NODES,
)


def test_preview_identity_binds_complete_ancestry_evidence(tmp_path: Path) -> None:
    with SExpressionWorkspace(tmp_path / "preview.db") as workspace:
        workspace.initialize("demo")
        created = workspace.create_program(
            "demo",
            "main",
            "main.weave",
            program_name="ancestry-limits",
        )
        workspace.create_branch("demo", "target", from_branch="main")
        workspace.create_branch("demo", "source", from_branch="main")
        workspace.create_form(
            "demo",
            "target",
            "main.weave",
            created["node_id"],
            "target-only",
        )
        workspace.create_form(
            "demo",
            "source",
            "main.weave",
            created["node_id"],
            "source-only",
        )

        preview = MergePreviewService(workspace).preview(
            "demo",
            "target",
            "source",
        )
        payload = {
            key: preview[key]
            for key in (
                "format",
                "project",
                "target_branch",
                "source_branch",
                "base_revision_id",
                "target_head_revision_id",
                "source_head_revision_id",
                "ancestry",
            )
        }

        assert preview["ancestry"]["limits"] == {
            "nodes": MAX_REVISION_DAG_NODES,
            "edges": MAX_REVISION_DAG_EDGES,
        }
        assert preview["ancestry"]["best_common_ancestors"] == [
            preview["base_revision_id"]
        ]
        assert workspace.db.hash_value(payload) == preview["preview_id"]

        changed = dict(payload)
        changed["ancestry"] = {
            **preview["ancestry"],
            "limits": {
                "nodes": MAX_REVISION_DAG_NODES - 1,
                "edges": MAX_REVISION_DAG_EDGES,
            },
        }
        assert workspace.db.hash_value(changed) != preview["preview_id"]
