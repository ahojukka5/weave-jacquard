from __future__ import annotations

from typing import Any

import pytest

from weave_frontend import ConflictError, ValidationError
from weave_frontend.merge_test_impact import (
    MergeCandidateTestImpactService as _MergeCandidateTestImpactService,
)

TARGET_HEAD = "revision-target"
SOURCE_HEAD = "revision-source"
BASE = "revision-base"
PREVIEW = "preview-exact"


def _root(value: str, **config: Any) -> dict[str, Any]:
    return {"kind": "fake", "id": f"n_{value}", "value": value, "config": config}


class _Workspace:
    def __init__(self) -> None:
        self.target_state = {
            "main.weave": _root("main-v1"),
            "support.weave": _root("support-v1"),
            "unused.weave": _root("unused-v1"),
            "@build-target/application": _root(
                "application-v1",
                document="main.weave",
                additional_documents=[],
            ),
            "@build-target/config": _root(
                "config-v1",
                document="support.weave",
                additional_documents=[],
            ),
            "@build-target/untested": _root(
                "untested-v1",
                document="unused.weave",
                additional_documents=[],
            ),
            "@test-target/smoke": _root("smoke-v1", build_target="application"),
            "@test-target/config-test": _root("config-test-v1", build_target="config"),
            "@test-target/removed": _root("removed-v1", build_target="config"),
        }
        self.merged_state = {
            "main.weave": _root("main-v2"),
            "support.weave": _root("support-v1"),
            "unused.weave": _root("unused-v2"),
            "@build-target/application": _root(
                "application-v1",
                document="main.weave",
                additional_documents=[],
            ),
            "@build-target/config": _root(
                "config-v2",
                document="support.weave",
                additional_documents=[],
            ),
            "@build-target/untested": _root(
                "untested-v2",
                document="unused.weave",
                additional_documents=[],
            ),
            "@test-target/smoke": _root("smoke-v1", build_target="application"),
            "@test-target/config-test": _root("config-test-v1", build_target="config"),
            "@test-target/new-test": _root("new-test-v1", build_target="config"),
        }
        self.db = self

    def _state_at_revision(self, revision_id: str) -> dict[str, Any]:
        assert revision_id == TARGET_HEAD
        return self.target_state

    @staticmethod
    def hash_value(value: Any) -> str:
        return _MergeCandidateTestImpactService._hash_json(value)


class _Previews:
    def __init__(self, workspace: _Workspace, *, conflicts: list[str] | None = None) -> None:
        self.workspace = workspace
        self.conflicts = conflicts or []

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
            "target_head_revision_id": TARGET_HEAD,
            "source_head_revision_id": SOURCE_HEAD,
            "base_revision_id": BASE,
            "preview_id": PREVIEW,
            "mergeable": not self.conflicts,
            "conflicts": list(self.conflicts),
            "merged_root_hash": "f" * 64 if not self.conflicts else None,
            "_merged_state": self.workspace.merged_state if not self.conflicts else None,
        }


class _BuildTargets:
    @staticmethod
    def _parse_tree(root: dict[str, Any], *, name: str) -> dict[str, Any]:
        return {"name": name, **root["config"]}

    @staticmethod
    def _require_program_documents(state: dict[str, Any], documents: list[str]) -> None:
        for document in documents:
            assert document in state


class _Tests:
    @staticmethod
    def _validate_name(name: str) -> str:
        if " " in name:
            raise ValidationError("INVALID_TEST_TARGET_NAME", "bad name")
        return name

    @staticmethod
    def _parse_tree(root: dict[str, Any], *, name: str) -> dict[str, Any]:
        return {"name": name, **root["config"]}

    @staticmethod
    def _require_build_target(state: dict[str, Any], name: str) -> None:
        assert f"@build-target/{name}" in state


def _service(
    *,
    conflicts: list[str] | None = None,
) -> tuple[_MergeCandidateTestImpactService, _Previews]:
    workspace = _Workspace()
    previews = _Previews(workspace, conflicts=conflicts)
    return (
        _MergeCandidateTestImpactService(previews, _BuildTargets(), _Tests()),
        previews,
    )


def test_merge_candidate_plan_binds_preview_and_structural_reasons() -> None:
    service, _ = _service()

    plan = service.page(
        "demo",
        "main",
        "feature",
        preview_id=PREVIEW,
        limit=10,
    )

    assert plan["format"] == "weave-merge-test-impact-plan-v1"
    assert plan["preview_id"] == PREVIEW
    assert plan["target_head_revision_id"] == TARGET_HEAD
    assert plan["source_head_revision_id"] == SOURCE_HEAD
    assert plan["base_revision_id"] == BASE
    assert plan["merged_root_hash"] == "f" * 64
    assert [item["name"] for item in plan["impacted_tests"]] == [
        "config-test",
        "new-test",
        "smoke",
    ]
    by_name = {item["name"]: item for item in plan["impacted_tests"]}
    assert by_name["config-test"]["reasons"] == ["build_target_changed"]
    assert by_name["new-test"]["reasons"] == [
        "test_definition_changed",
        "build_target_changed",
    ]
    assert by_name["smoke"]["reasons"] == ["source_changed"]
    assert by_name["smoke"]["changed_source_documents"] == ["main.weave"]
    assert all(
        item["definition_subject"] == {
            "kind": "virtual_merge_candidate",
            "preview_id": PREVIEW,
            "committed_revision_id": None,
        }
        for item in plan["impacted_tests"]
    )
    assert plan["changed_program_documents"] == ["main.weave", "unused.weave"]
    assert plan["changed_build_targets"] == ["config", "untested"]
    assert plan["changed_test_targets"] == ["new-test", "removed"]
    assert plan["removed_test_targets"] == ["removed"]
    assert plan["removed_build_targets"] == []
    assert plan["uncovered_changed_program_documents"] == ["unused.weave"]
    assert plan["untested_changed_build_targets"] == ["untested"]
    assert plan["complete_selection"] is True
    assert plan["candidate_execution"] == {
        "tool": "branch_merge_test_batch_run",
        "arguments": {
            "project": "demo",
            "target_branch": "main",
            "source_branch": "feature",
            "test_targets": ["config-test", "new-test", "smoke"],
            "preview_id": PREVIEW,
        },
    }
    assert plan["interpretation"] == {
        "kind": "virtual_merge_structural_candidate_plan",
        "executes_tests": False,
        "publishes_merge": False,
        "claims_correctness": False,
        "claims_complete_semantic_coverage": False,
        "ordinary_test_batch_compatible": False,
        "candidate_test_batch_compatible": True,
        "caller_order": "lexical_pagination_only",
    }


def test_merge_candidate_plan_pages_under_one_stable_identity() -> None:
    service, _ = _service()

    first = service.page("demo", "main", "feature", limit=2)
    second = service.page(
        "demo",
        "main",
        "feature",
        start_after_name=first["next_after_name"],
        limit=2,
    )

    assert first["plan_id"] == second["plan_id"]
    assert [item["name"] for item in first["impacted_tests"]] == [
        "config-test",
        "new-test",
    ]
    assert first["impacted_tests_truncated"] is True
    assert first["next_after_name"] == "new-test"
    assert first["candidate_execution"] is None
    assert first["interpretation"]["candidate_test_batch_compatible"] is False
    assert [item["name"] for item in second["impacted_tests"]] == ["smoke"]
    assert second["impacted_tests_truncated"] is False
    assert second["candidate_execution"] is None
    assert second["interpretation"]["candidate_test_batch_compatible"] is False


def test_merge_candidate_plan_rejects_conflicts_and_stale_preview() -> None:
    conflicted, _ = _service(conflicts=["main.weave:n_1"])
    with pytest.raises(ConflictError):
        conflicted.page("demo", "main", "feature")

    service, _ = _service()
    with pytest.raises(ValidationError) as raised:
        service.page(
            "demo",
            "main",
            "feature",
            preview_id="preview-stale",
        )
    assert raised.value.code == "STALE_MERGE_PREVIEW"


def test_merge_candidate_plan_rejects_missing_clean_candidate_state() -> None:
    service, previews = _service()
    original = previews.candidate

    def missing_state(*args: Any, **kwargs: Any) -> dict[str, Any]:
        candidate = original(*args, **kwargs)
        candidate["_merged_state"] = None
        return candidate

    previews.candidate = missing_state  # type: ignore[method-assign]
    with pytest.raises(ValidationError) as raised:
        service.page("demo", "main", "feature")
    assert raised.value.code == "INVALID_MERGE_CANDIDATE"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": 0},
        {"limit": 101},
        {"limit": True},
        {"evidence_limit": 0},
        {"evidence_limit": 501},
    ],
)
def test_merge_candidate_plan_validates_bounds(kwargs: dict[str, Any]) -> None:
    service, _ = _service()

    with pytest.raises(ValidationError) as raised:
        service.page("demo", "main", "feature", **kwargs)

    assert raised.value.code == "INVALID_MERGE_TEST_IMPACT_LIMIT"
