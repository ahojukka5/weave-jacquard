from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from weave_frontend.compiler import CompilerBridge
from weave_frontend.errors import ArtifactIntegrityError
from weave_frontend.merge_candidate_build import MergeCandidateBuildService
from weave_frontend.merge_candidate_test_runs import MergeCandidateTestBatchService
from weave_frontend.merge_preview import MERGE_PREVIEW_FORMAT
from weave_frontend.metadata_build_targets import BuildTargetRegistry
from weave_frontend.sandbox import SandboxLimits, SandboxResult
from weave_frontend.sexpr import make_atom, make_form
from weave_frontend.test_target_views import VerifiedTestTargetRegistry
from weave_frontend.test_targets import TestTargetRegistry

BASE = "revision-base"
TARGET = "revision-target"
SOURCE = "revision-source"


class _DB:
    def __init__(self, path: Path) -> None:
        self.path = path

    @staticmethod
    def hash_value(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


class _Workspace:
    def __init__(self, path: Path, target_state: dict[str, Any], state: dict[str, Any]) -> None:
        self.db = _DB(path)
        self.states = {BASE: target_state, TARGET: target_state, SOURCE: state}
        self.heads = {"main": TARGET, "feature": SOURCE}

    def branch_head(self, project: str, branch: str) -> str:
        assert project == "demo"
        return self.heads[branch]

    def _state_at_revision(self, revision_id: str) -> dict[str, Any]:
        return self.states[revision_id]

    @staticmethod
    def _common_ancestor(left: str, right: str) -> str:
        assert {left, right} == {TARGET, SOURCE}
        return BASE

    def _merge_states(
        self,
        base: dict[str, Any],
        target: dict[str, Any],
        source: dict[str, Any],
    ) -> tuple[dict[str, Any], set[str]]:
        assert base is self.states[BASE]
        assert target is self.states[TARGET]
        assert source is self.states[SOURCE]
        return source, {"main.weave"}

    @staticmethod
    def _validate_state(state: dict[str, Any]) -> None:
        assert "main.weave" in state


class _Previews:
    def __init__(self, workspace: _Workspace) -> None:
        self.workspace = workspace

    def candidate(
        self,
        project: str,
        target_branch: str,
        source_branch: str,
    ) -> dict[str, Any]:
        payload = {
            "format": MERGE_PREVIEW_FORMAT,
            "project": project,
            "target_branch": target_branch,
            "source_branch": source_branch,
            "base_revision_id": BASE,
            "target_head_revision_id": TARGET,
            "source_head_revision_id": SOURCE,
        }
        state = self.workspace.states[SOURCE]
        return {
            **payload,
            "preview_id": self.workspace.db.hash_value(payload),
            "mergeable": True,
            "conflicts": [],
            "merged_root_hash": self.workspace.db.hash_value(state),
            "_merged_state": state,
        }


class _Compiler(CompilerBridge):
    def _require_project_revision(self, project: str, revision_id: str) -> str:
        assert project == "demo"
        return self.workspace.db.hash_value(self.workspace.states[revision_id])


class _Sandbox:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, list[str], bytes, SandboxLimits]] = []

    @staticmethod
    def capabilities() -> dict[str, Any]:
        return {
            "format": "weave-sandbox-capabilities-v1",
            "backend": "test-sandbox",
            "available": True,
            "version": "test-sandbox 1",
            "probe_error": None,
            "policy": {
                "network": "deny",
                "filesystem": "isolated",
                "seccomp": False,
            },
            "policy_hash": "a" * 64,
            "resource_limits": {"process_count": False},
        }

    def run(
        self,
        executable: Path,
        arguments: list[str],
        stdin: bytes,
        limits: SandboxLimits,
    ) -> SandboxResult:
        self.calls.append((executable, arguments, stdin, limits))
        return SandboxResult(
            returncode=7,
            signal=None,
            termination_reason="exit",
            timed_out=False,
            output_limited=False,
            duration_ms=4,
            stdout=b"done\n",
            stderr=b"warning\n",
        )


def _program(version: str) -> dict[str, Any]:
    root = make_form("program")
    name = make_form("name")
    name["children"].append(make_atom("string", "demo"))
    version_form = make_form("version")
    version_form["children"].append(make_atom("string", version))
    root["children"].extend([name, version_form])
    return root


def _state() -> tuple[dict[str, Any], dict[str, Any]]:
    target = BuildTargetRegistry._build_tree(
        "main.weave",
        [],
        "native",
        existing=None,
    )
    passing_config = TestTargetRegistry._config(
        "passing",
        "application",
        arguments=[],
        stdin="",
        expected_exit_code=7,
        expected_stdout="done\n",
        expected_stderr="warning\n",
        timeout_ms=2_000,
        max_memory_bytes=64 * 1024 * 1024,
        max_output_bytes=8_192,
        max_file_bytes=4_096,
        tags=["smoke"],
    )
    failing_config = {
        **passing_config,
        "name": "failing",
        "expected_stdout": "incorrect\n",
    }
    metadata = {
        "@build-target/application": target,
        "@test-target/passing": TestTargetRegistry._build_tree(
            passing_config,
            existing=None,
        ),
        "@test-target/failing": TestTargetRegistry._build_tree(
            failing_config,
            existing=None,
        ),
    }
    target_state = {"main.weave": _program("0.1"), **metadata}
    candidate_state = {"main.weave": _program("0.2"), **metadata}
    return target_state, candidate_state


def _fake_compiler(path: Path) -> Path:
    path.write_text(
        r'''#!/usr/bin/env python3
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

def main() -> int:
    output_index = sys.argv.index("-o")
    manifest_index = sys.argv.index("--manifest-json")
    diagnostics_index = sys.argv.index("--diagnostics-json")
    sources = [Path(value).resolve() for value in sys.argv[2:output_index]]
    output = Path(sys.argv[output_index + 1]).resolve()
    manifest = Path(sys.argv[manifest_index + 1]).resolve()
    diagnostics = Path(sys.argv[diagnostics_index + 1]).resolve()
    output.write_text(
        "#!/bin/sh\nprintf 'done\\n'\nprintf 'warning\\n' >&2\nexit 7\n",
        encoding="utf-8",
    )
    os.chmod(output, 0o755)
    write(manifest, {
        "format": "weavec-build-manifest-v1",
        "status": "succeeded",
        "phase": "complete",
        "target": "x86_64-unknown-linux-gnu",
        "compiler": str(Path(sys.argv[0]).resolve()),
        "runtime": "/opt/weavec/libweave-runtime.a",
        "codegen": "clang",
        "linker": "clang",
        "output": str(output),
        "sources": [str(source) for source in sources],
    })
    write(diagnostics, {
        "format": "weavec-diagnostics-v1",
        "status": "succeeded",
        "phase": "complete",
        "exit_code": 0,
        "raw_exit_code": 0,
        "diagnostics": [],
    })
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
''',
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _services(tmp_path: Path) -> tuple[
    MergeCandidateBuildService,
    MergeCandidateTestBatchService,
    _Previews,
    _Sandbox,
]:
    target_state, candidate_state = _state()
    workspace = _Workspace(tmp_path / "jacquard.db", target_state, candidate_state)
    previews = _Previews(workspace)
    targets = BuildTargetRegistry(workspace)
    tests = VerifiedTestTargetRegistry(workspace)
    compiler = _Compiler(
        workspace,
        compiler=_fake_compiler(tmp_path / "weavec"),
        build_root=tmp_path / "builds",
    )
    builds = MergeCandidateBuildService(
        previews,
        targets,
        compiler,
        build_root=tmp_path / "candidate-builds",
    )
    sandbox = _Sandbox()
    runs = MergeCandidateTestBatchService(
        previews,
        tests,
        builds,
        sandbox,
        run_root=tmp_path / "candidate-runs",
    )
    return builds, runs, previews, sandbox


def test_candidate_build_is_content_derived_cached_and_verified(tmp_path: Path) -> None:
    builds, _, previews, _ = _services(tmp_path)
    preview = previews.candidate("demo", "main", "feature")

    first = builds.build(
        "demo",
        "main",
        "feature",
        "application",
        preview_id=preview["preview_id"],
    )
    repeated = builds.build(
        "demo",
        "main",
        "feature",
        "application",
        preview_id=preview["preview_id"],
    )

    assert first["status"] == "succeeded"
    assert first["subject"]["committed_revision_id"] is None
    assert first["subject"]["preview_id"] == preview["preview_id"]
    assert first["subject"]["merged_root_hash"] == preview["merged_root_hash"]
    assert first["build_target"]["name"] == "application"
    assert first["build_id"] == repeated["build_id"]
    assert repeated["cached"] is True
    assert first["artifact_paths"]["executable"].endswith("program")

    executable = Path(first["artifact_paths"]["executable"])
    executable.write_bytes(b"tampered")
    with pytest.raises(ArtifactIntegrityError):
        builds.get(first["build_id"])


def test_candidate_batch_reuses_build_and_retains_behavioral_failure(
    tmp_path: Path,
) -> None:
    builds, runs, previews, sandbox = _services(tmp_path)
    preview = previews.candidate("demo", "main", "feature")

    qualification = runs.run(
        "demo",
        "main",
        "feature",
        ["passing", "failing"],
        preview_id=preview["preview_id"],
    )
    repeated = runs.get(qualification["qualification_id"])

    assert qualification["status"] == "failed"
    assert qualification["all_passed"] is False
    assert qualification["passed_test_count"] == 1
    assert qualification["failed_test_count"] == 1
    assert qualification["error_test_count"] == 0
    assert qualification["heads_unchanged_at_completion"] is True
    assert [item["outcome"] for item in qualification["results"]] == [
        "passed",
        "failed",
    ]
    assert len(qualification["builds"]) == 1
    assert len(sandbox.calls) == 2
    assert qualification["manifest_sha256"] == repeated["manifest_sha256"]
    assert builds.get(qualification["builds"][0]["build_id"])["status"] == "succeeded"

    page = runs.output_page(
        qualification["qualification_id"],
        "passing",
        "stdout",
        max_bytes=2,
    )
    assert page["utf8_text"] == "do"
    assert page["next_byte"] == 2

    manifest_path = (
        tmp_path
        / "candidate-runs"
        / qualification["qualification_id"]
        / "qualification-manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["passed_test_count"] = 0
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ArtifactIntegrityError, match="passed count"):
        runs.get(qualification["qualification_id"])
