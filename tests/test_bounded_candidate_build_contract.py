from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

from weave_frontend.bounded_merge_candidate_build import (
    MergeCandidateBuildService as BoundedMergeCandidateBuildService,
)
from weave_frontend.errors import ArtifactIntegrityError
from weave_frontend.verified_merge_candidate_build import MergeCandidateBuildService

ROOT = Path(__file__).resolve().parents[1]


def _candidate_test_module() -> ModuleType:
    path = ROOT / "tests" / "test_merge_candidate_test_runs.py"
    spec = importlib.util.spec_from_file_location(
        "_jacquard_candidate_fixture",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.MergeCandidateBuildService = BoundedMergeCandidateBuildService
    return module


def test_production_mcp_routes_candidate_builds_through_bounded_service() -> None:
    from weave_frontend import mcp_merge_candidate_test_runs as production

    assert production.MergeCandidateBuildService is MergeCandidateBuildService


def test_candidate_output_limit_changes_build_identity(tmp_path: Path) -> None:
    fixture = _candidate_test_module()
    builds, _, previews, _ = fixture._services(tmp_path)
    assert isinstance(builds, BoundedMergeCandidateBuildService)
    preview = previews.candidate("demo", "main", "feature")

    builds.compiler.max_output_bytes = 1_024
    first = builds.build(
        "demo",
        "main",
        "feature",
        "application",
        preview_id=preview["preview_id"],
    )
    builds.compiler.max_output_bytes = 2_048
    second = builds.build(
        "demo",
        "main",
        "feature",
        "application",
        preview_id=preview["preview_id"],
    )

    assert first["status"] == "succeeded"
    assert second["status"] == "succeeded"
    assert first["compiler_output_limit_bytes"] == 1_024
    assert second["compiler_output_limit_bytes"] == 2_048
    assert first["output_limited"] is False
    assert second["output_limited"] is False
    assert first["build_id"] != second["build_id"]
    assert first["build_input_hash"] != second["build_input_hash"]


def test_candidate_limit_and_termination_tampering_is_rejected(tmp_path: Path) -> None:
    fixture = _candidate_test_module()
    builds, _, previews, _ = fixture._services(tmp_path)
    preview = previews.candidate("demo", "main", "feature")
    result = builds.build(
        "demo",
        "main",
        "feature",
        "application",
        preview_id=preview["preview_id"],
    )
    manifest_path = Path(result["build_directory"]) / "manifest.json"
    original = json.loads(manifest_path.read_text(encoding="utf-8"))

    tampered = dict(original)
    tampered["compiler_output_limit_bytes"] += 1
    manifest_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ArtifactIntegrityError, match="input hash"):
        builds.get(result["build_id"])

    tampered = dict(original)
    tampered["output_limited"] = True
    manifest_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ArtifactIntegrityError, match="output-limit flag"):
        builds.get(result["build_id"])
