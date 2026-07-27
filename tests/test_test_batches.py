from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from weave_frontend import ValidationError
from weave_frontend.errors import ArtifactIntegrityError, NotFoundError
from weave_frontend.test_batches import MAX_TEST_BATCH_TARGETS, TestBatchService


class _Workspace:
    def branch_head(self, project: str, branch: str) -> str:
        assert (project, branch) == ("demo", "main")
        return "revision-exact"


class _Tests:
    def __init__(self, names: tuple[str, ...] = ("alpha", "beta", "broken")) -> None:
        self.names = set(names)
        self.calls: list[str] = []

    def get(
        self,
        project: str,
        name: str,
        *,
        branch: str,
        revision_id: str,
    ) -> dict[str, Any]:
        assert (project, branch, revision_id) == ("demo", "main", "revision-exact")
        self.calls.append(name)
        if name not in self.names:
            raise NotFoundError(f"test target {name!r} not found")
        return {"name": name, "definition_hash": (name[0] * 64)}


class _Runs:
    def __init__(self, root: Path, *, available: bool = True) -> None:
        self.run_root = root
        self.run_root.mkdir(parents=True)
        self.available = available
        self.calls: list[str] = []
        self.retained: dict[str, dict[str, Any]] = {}

    def capabilities(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "probe_error": None if self.available else "disabled",
            "backend": "fake",
            "version": "fake 1",
            "policy_hash": "p" * 64,
            "policy": {"network": "deny"},
            "resource_limits": {"process_count": False},
        }

    def run(
        self,
        project: str,
        name: str,
        *,
        branch: str,
        revision_id: str,
    ) -> dict[str, Any]:
        assert (project, branch, revision_id) == ("demo", "main", "revision-exact")
        self.calls.append(name)
        if name == "broken":
            raise ValidationError("TEST_BUILD_FAILED", "fake build failed")
        passed = name == "alpha"
        run_id = f"{len(self.retained) + 1:032x}"
        run = {
            "run_id": run_id,
            "manifest_sha256": name[0] * 64,
            "definition_hash": name[0] * 64,
            "passed": passed,
        }
        self.retained[run_id] = run
        return dict(run)

    def get(self, run_id: str) -> dict[str, Any]:
        return dict(self.retained[run_id])


def _service(
    tmp_path: Path,
    *,
    tests: _Tests | None = None,
    runs: _Runs | None = None,
) -> tuple[TestBatchService, _Tests, _Runs]:
    resolved_tests = tests or _Tests()
    resolved_runs = runs or _Runs(tmp_path / "runs")
    return (
        TestBatchService(_Workspace(), resolved_tests, resolved_runs),
        resolved_tests,
        resolved_runs,
    )


def test_batch_preserves_order_and_retains_pass_and_failure_evidence(
    tmp_path: Path,
) -> None:
    service, tests, runs = _service(tmp_path)

    batch = service.run("demo", ["beta", "alpha"], branch="main")
    repeated = service.get(batch["batch_id"])

    assert tests.calls == ["beta", "alpha"]
    assert runs.calls == ["beta", "alpha"]
    assert batch["test_targets"] == ["beta", "alpha"]
    assert [item["outcome"] for item in batch["results"]] == ["failed", "passed"]
    assert batch["status"] == "failed"
    assert batch["all_passed"] is False
    assert batch["selected_test_count"] == 2
    assert batch["passed_test_count"] == 1
    assert batch["failed_test_count"] == 1
    assert batch["error_test_count"] == 0
    assert batch["sandbox"]["policy_hash"] == "p" * 64
    assert repeated["manifest_sha256"] == batch["manifest_sha256"]
    assert list((tmp_path / "runs" / "batches").glob("*/batch-manifest.json"))


def test_batch_retains_independent_domain_errors_as_incomplete(tmp_path: Path) -> None:
    service, _, runs = _service(tmp_path)

    batch = service.run("demo", ["alpha", "broken", "beta"])

    assert runs.calls == ["alpha", "broken", "beta"]
    assert batch["status"] == "incomplete"
    assert batch["passed_test_count"] == 1
    assert batch["failed_test_count"] == 1
    assert batch["error_test_count"] == 1
    error = batch["results"][1]
    assert error["outcome"] == "error"
    assert error["run_id"] if "run_id" in error else True
    assert error["error"]["code"] == "TEST_BUILD_FAILED"
    assert error["passed"] is None


def test_all_definitions_are_resolved_before_any_execution(tmp_path: Path) -> None:
    tests = _Tests(names=("alpha",))
    runs = _Runs(tmp_path / "runs")
    service, _, _ = _service(tmp_path, tests=tests, runs=runs)

    with pytest.raises(NotFoundError):
        service.run("demo", ["alpha", "missing"])

    assert tests.calls == ["alpha", "missing"]
    assert runs.calls == []
    assert list((tmp_path / "runs" / "batches").iterdir()) == []


def test_unavailable_sandbox_refuses_whole_batch_before_execution(tmp_path: Path) -> None:
    runs = _Runs(tmp_path / "runs", available=False)
    service, tests, _ = _service(tmp_path, runs=runs)

    with pytest.raises(ValidationError) as raised:
        service.run("demo", ["alpha", "beta"])

    assert raised.value.code == "SANDBOX_UNAVAILABLE"
    assert tests.calls == ["alpha", "beta"]
    assert runs.calls == []


@pytest.mark.parametrize(
    "selection",
    [
        None,
        (),
        [],
        ["bad name"],
        ["alpha", "alpha"],
        ["alpha"] * (MAX_TEST_BATCH_TARGETS + 1),
    ],
)
def test_batch_selection_is_explicit_unique_and_bounded(
    tmp_path: Path,
    selection: Any,
) -> None:
    service, _, runs = _service(tmp_path)

    with pytest.raises(ValidationError) as raised:
        service.run("demo", selection)  # type: ignore[arg-type]

    assert raised.value.code == "INVALID_TEST_BATCH_SELECTION"
    assert runs.calls == []


def test_batch_get_rejects_tampered_manifest_and_subordinate_evidence(
    tmp_path: Path,
) -> None:
    service, _, runs = _service(tmp_path)
    batch = service.run("demo", ["alpha"])
    manifest_path = next((tmp_path / "runs" / "batches").glob("*/batch-manifest.json"))
    original = json.loads(manifest_path.read_text(encoding="utf-8"))

    original["passed_test_count"] = 0
    manifest_path.write_text(json.dumps(original), encoding="utf-8")
    with pytest.raises(ArtifactIntegrityError, match="passed count"):
        service.get(batch["batch_id"])

    original["passed_test_count"] = 1
    manifest_path.write_text(json.dumps(original), encoding="utf-8")
    run_id = batch["results"][0]["run_id"]
    runs.retained[run_id]["manifest_sha256"] = "0" * 64
    with pytest.raises(ArtifactIntegrityError, match="run manifest hash"):
        service.get(batch["batch_id"])
