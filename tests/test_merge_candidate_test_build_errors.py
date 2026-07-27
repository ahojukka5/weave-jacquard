from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from weave_frontend.errors import ArtifactIntegrityError
from weave_frontend.verified_merge_candidate_test_runs import (
    MergeCandidateTestBatchService as _MergeCandidateTestBatchService,
)

PREVIEW_ID = "a" * 64
BUILD_ID = "b" * 32
BUILD_INPUT_HASH = "c" * 64
BUILD_MANIFEST_HASH = "d" * 64


class _DB:
    def __init__(self, path: Path) -> None:
        self.path = path

    @staticmethod
    def hash_value(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


class _Workspace:
    def __init__(self, path: Path) -> None:
        self.db = _DB(path)
        self.state = {
            "@test-target/broken": {
                "id": "n_broken",
                "config": {"name": "broken", "build_target": "application"},
            }
        }
        self.heads = {"main": "revision-target", "feature": "revision-source"}

    def branch_head(self, project: str, branch: str) -> str:
        assert project == "demo"
        return self.heads[branch]


class _Previews:
    def __init__(self, workspace: _Workspace) -> None:
        self.workspace = workspace

    def candidate(
        self,
        project: str,
        target_branch: str,
        source_branch: str,
    ) -> dict[str, Any]:
        assert (project, target_branch, source_branch) == (
            "demo",
            "main",
            "feature",
        )
        return {
            "project": project,
            "target_branch": target_branch,
            "source_branch": source_branch,
            "base_revision_id": "revision-base",
            "target_head_revision_id": "revision-target",
            "source_head_revision_id": "revision-source",
            "preview_id": PREVIEW_ID,
            "merged_root_hash": "e" * 64,
            "mergeable": True,
            "conflicts": [],
            "_merged_state": self.workspace.state,
        }


class _Tests:
    @staticmethod
    def _validate_name(name: str) -> str:
        return name

    @staticmethod
    def _storage_document(name: str) -> str:
        return f"@test-target/{name}"

    @staticmethod
    def _parse_tree(root: dict[str, Any], *, name: str) -> dict[str, Any]:
        assert root["config"]["name"] == name
        return dict(root["config"])

    @staticmethod
    def _require_build_target(state: dict[str, Any], name: str) -> None:
        assert state
        assert name == "application"


class _Builds:
    def __init__(self, workspace: _Workspace) -> None:
        self.workspace = workspace
        self.subject = {
            "kind": "virtual_merge_candidate",
            "project": "demo",
            "target_branch": "main",
            "source_branch": "feature",
            "base_revision_id": "revision-base",
            "target_head_revision_id": "revision-target",
            "source_head_revision_id": "revision-source",
            "preview_id": PREVIEW_ID,
            "merged_root_hash": "e" * 64,
            "committed_revision_id": None,
        }
        self.build = {
            "build_id": BUILD_ID,
            "build_input_hash": BUILD_INPUT_HASH,
            "manifest_sha256": BUILD_MANIFEST_HASH,
            "status": "failed",
            "subject": self.subject,
            "build_target": {"name": "application"},
        }

    def _subject(self, candidate: dict[str, Any]) -> dict[str, Any]:
        assert candidate["preview_id"] == PREVIEW_ID
        return dict(self.subject)

    def build_exact(
        self,
        candidate: dict[str, Any],
        state: dict[str, Any],
        build_target: str,
    ) -> dict[str, Any]:
        assert candidate["preview_id"] == PREVIEW_ID
        assert state is self.workspace.state
        assert build_target == "application"
        return dict(self.build)

    def _reconstruct_subject_state(self, subject: dict[str, Any]) -> dict[str, Any]:
        assert subject == self.subject
        return self.workspace.state

    def get(self, build_id: str) -> dict[str, Any]:
        assert build_id == BUILD_ID
        return dict(self.build)


class _Sandbox:
    run_called = False

    @staticmethod
    def capabilities() -> dict[str, Any]:
        return {
            "backend": "test-sandbox",
            "available": True,
            "version": "test-sandbox 1",
            "probe_error": None,
            "policy": {"network": "deny", "filesystem": "isolated"},
            "policy_hash": "f" * 64,
            "resource_limits": {"process_count": False},
        }

    def run(self, *args: Any, **kwargs: Any) -> Any:
        self.run_called = True
        raise AssertionError("failed candidate builds must not execute")


def test_all_build_errors_publish_verified_artifact_free_aggregate(
    tmp_path: Path,
) -> None:
    workspace = _Workspace(tmp_path / "jacquard.db")
    sandbox = _Sandbox()
    service = _MergeCandidateTestBatchService(
        _Previews(workspace),
        _Tests(),
        _Builds(workspace),
        sandbox,
        run_root=tmp_path / "candidate-runs",
    )

    result = service.run(
        "demo",
        "main",
        "feature",
        ["broken"],
        preview_id=PREVIEW_ID,
    )
    repeated = service.get(result["qualification_id"])

    assert sandbox.run_called is False
    assert result["status"] == "incomplete"
    assert result["passed_test_count"] == 0
    assert result["failed_test_count"] == 0
    assert result["error_test_count"] == 1
    assert result["results"][0]["outcome"] == "error"
    assert result["artifacts"] == {}
    assert result["artifact_sha256"] == {}
    assert repeated["manifest_sha256"] == result["manifest_sha256"]

    manifest_path = (
        tmp_path
        / "candidate-runs"
        / result["qualification_id"]
        / "qualification-manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifact_sha256"] = {"invented.bin": "0" * 64}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ArtifactIntegrityError, match="artifact-free"):
        service.get(result["qualification_id"])
