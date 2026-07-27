from __future__ import annotations

from typing import Any

import pytest

from weave_frontend import ValidationError
from weave_frontend.test_impact import TestImpactPlanService as _TestImpactPlanService

BASE = "revision-base"
TARGET = "revision-target"


def _root(value: str) -> dict[str, Any]:
    return {"kind": "list", "id": f"n_{value}", "items": [{"kind": "atom", "value": value}]}


class _Workspace:
    def __init__(self) -> None:
        self.states = {
            BASE: {
                "main.weave": _root("main-v1"),
                "support.weave": _root("support"),
                "unused.weave": _root("unused-v1"),
                "@build-target/application": _root("application"),
                "@build-target/stable": _root("stable"),
                "@build-target/config": _root("config-v1"),
                "@build-target/untested": _root("untested-v1"),
                "@test-target/smoke": _root("smoke"),
                "@test-target/definition": _root("definition-v1"),
                "@test-target/target-config": _root("target-config"),
                "@test-target/removed": _root("removed"),
            },
            TARGET: {
                "main.weave": _root("main-v2"),
                "support.weave": _root("support"),
                "unused.weave": _root("unused-v2"),
                "@build-target/application": _root("application"),
                "@build-target/stable": _root("stable"),
                "@build-target/config": _root("config-v2"),
                "@build-target/untested": _root("untested-v2"),
                "@test-target/smoke": _root("smoke"),
                "@test-target/definition": _root("definition-v2"),
                "@test-target/target-config": _root("target-config"),
                "@test-target/new-test": _root("new-test"),
            },
        }

    def branch_head(self, project: str, branch: str) -> str:
        assert (project, branch) == ("demo", "main")
        return TARGET

    def _state_at_revision(self, revision_id: str) -> dict[str, Any]:
        return self.states[revision_id]


class _Targets:
    def list(
        self,
        project: str,
        *,
        branch: str,
        revision_id: str,
    ) -> list[dict[str, Any]]:
        assert (project, branch) == ("demo", "main")
        common = [
            {
                "name": "application",
                "document": "main.weave",
                "additional_documents": [],
            },
            {
                "name": "stable",
                "document": "support.weave",
                "additional_documents": [],
            },
            {
                "name": "config",
                "document": "support.weave",
                "additional_documents": [],
            },
            {
                "name": "untested",
                "document": "unused.weave",
                "additional_documents": [],
            },
        ]
        assert revision_id in {BASE, TARGET}
        return common


class _Tests:
    def _require_project_revision(self, project: str, revision_id: str) -> None:
        assert project == "demo"
        if revision_id not in {BASE, TARGET}:
            raise AssertionError(revision_id)

    @staticmethod
    def _validate_name(name: str) -> str:
        if " " in name:
            raise ValidationError("INVALID_TEST_TARGET_NAME", "bad test name")
        return name

    def list(
        self,
        project: str,
        *,
        branch: str,
        revision_id: str,
    ) -> list[dict[str, Any]]:
        assert (project, branch) == ("demo", "main")
        if revision_id == BASE:
            bindings = {
                "smoke": "application",
                "definition": "stable",
                "target-config": "config",
                "removed": "stable",
            }
        else:
            bindings = {
                "smoke": "application",
                "definition": "stable",
                "target-config": "config",
                "new-test": "stable",
            }
        return [
            {
                "name": name,
                "build_target": target,
                "definition_hash": (f"{index:x}" * 64)[:64],
            }
            for index, (name, target) in enumerate(sorted(bindings.items()), start=1)
        ]


def _service() -> _TestImpactPlanService:
    return _TestImpactPlanService(_Workspace(), _Targets(), _Tests())


def test_impact_plan_explains_exact_structural_reasons_and_gaps() -> None:
    plan = _service().page(
        "demo",
        BASE,
        target_revision_id=TARGET,
        limit=10,
    )

    assert plan["format"] == "weave-test-impact-plan-v1"
    assert plan["base_revision_id"] == BASE
    assert plan["target_revision_id"] == TARGET
    assert plan["total_impacted_test_count"] == 4
    assert [item["name"] for item in plan["impacted_tests"]] == [
        "definition",
        "new-test",
        "smoke",
        "target-config",
    ]
    by_name = {item["name"]: item for item in plan["impacted_tests"]}
    assert by_name["definition"]["reasons"] == ["test_definition_changed"]
    assert by_name["new-test"]["reasons"] == ["test_definition_changed"]
    assert by_name["smoke"]["reasons"] == ["source_changed"]
    assert by_name["smoke"]["changed_source_documents"] == ["main.weave"]
    assert by_name["target-config"]["reasons"] == ["build_target_changed"]
    assert plan["changed_program_documents"] == ["main.weave", "unused.weave"]
    assert plan["changed_build_targets"] == ["config", "untested"]
    assert plan["changed_test_targets"] == ["definition", "new-test", "removed"]
    assert plan["removed_test_targets"] == ["removed"]
    assert plan["removed_build_targets"] == []
    assert plan["uncovered_changed_program_documents"] == ["unused.weave"]
    assert plan["untested_changed_build_targets"] == ["untested"]
    assert plan["complete_selection"] is True
    assert plan["test_batch_run"] == {
        "tool": "test_batch_run",
        "arguments": {
            "project": "demo",
            "test_targets": ["definition", "new-test", "smoke", "target-config"],
            "branch": "main",
            "revision_id": TARGET,
        },
    }
    assert plan["interpretation"] == {
        "kind": "structural_candidate_plan",
        "executes_tests": False,
        "claims_correctness": False,
        "claims_complete_semantic_coverage": False,
        "caller_order": "lexical_pagination_only",
    }


def test_impact_plan_pagination_preserves_one_stable_identity() -> None:
    service = _service()

    first = service.page("demo", BASE, target_revision_id=TARGET, limit=2)
    second = service.page(
        "demo",
        BASE,
        target_revision_id=TARGET,
        start_after_name=first["next_after_name"],
        limit=2,
    )
    complete = service.page("demo", BASE, target_revision_id=TARGET, limit=10)

    assert first["plan_id"] == second["plan_id"] == complete["plan_id"]
    assert [item["name"] for item in first["impacted_tests"]] == [
        "definition",
        "new-test",
    ]
    assert first["impacted_tests_truncated"] is True
    assert first["next_after_name"] == "new-test"
    assert first["complete_selection"] is False
    assert first["test_batch_run"] is None
    assert [item["name"] for item in second["impacted_tests"]] == [
        "smoke",
        "target-config",
    ]
    assert second["impacted_tests_truncated"] is False
    assert second["complete_selection"] is False
    assert second["test_batch_run"] is None


def test_same_revision_produces_complete_empty_plan() -> None:
    plan = _service().page("demo", BASE, target_revision_id=BASE)

    assert plan["total_impacted_test_count"] == 0
    assert plan["impacted_tests"] == []
    assert plan["changed_program_documents_count"] == 0
    assert plan["complete_selection"] is True
    assert plan["test_batch_run"] is None


def test_target_branch_head_is_captured_when_revision_is_omitted() -> None:
    plan = _service().page("demo", BASE)

    assert plan["target_revision_id"] == TARGET


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"limit": 0}, "INVALID_TEST_IMPACT_LIMIT"),
        ({"limit": 101}, "INVALID_TEST_IMPACT_LIMIT"),
        ({"limit": True}, "INVALID_TEST_IMPACT_LIMIT"),
        ({"evidence_limit": 0}, "INVALID_TEST_IMPACT_LIMIT"),
        ({"evidence_limit": 501}, "INVALID_TEST_IMPACT_LIMIT"),
        ({"start_after_name": "bad name"}, "INVALID_TEST_TARGET_NAME"),
    ],
)
def test_impact_plan_validates_bounds_and_cursor(
    kwargs: dict[str, Any],
    code: str,
) -> None:
    with pytest.raises(ValidationError) as raised:
        _service().page("demo", BASE, target_revision_id=TARGET, **kwargs)

    assert raised.value.code == code
