from __future__ import annotations

from pathlib import Path

import pytest

from weave_frontend import SExpressionWorkspace, ValidationError
from weave_frontend.builds import MetadataBuildTargetRegistry as BuildTargetRegistry
from weave_frontend.test_target_views import (
    MAX_TEST_TARGET_PAGE_SIZE,
    TEST_TARGET_LIST_FORMAT,
    VerifiedTestTargetRegistry,
)
from weave_frontend.test_target_views import (
    TestTargetPageService as _TestTargetPageService,
)


def _services(
    path: Path,
) -> tuple[
    SExpressionWorkspace,
    VerifiedTestTargetRegistry,
    _TestTargetPageService,
    str,
]:
    workspace = SExpressionWorkspace(path)
    workspace.initialize("demo")
    program = workspace.create_program(
        "demo",
        "main",
        "main.weave",
        program_name="test-target-views",
    )
    target = BuildTargetRegistry(workspace).set(
        "demo",
        "main",
        "application",
        "main.weave",
        expected_revision_id=program["revision_id"],
    )
    registry = VerifiedTestTargetRegistry(workspace)
    return (
        workspace,
        registry,
        _TestTargetPageService(registry),
        target["revision_id"],
    )


def test_verified_reads_and_writes_return_deterministic_definition_hash(
    tmp_path: Path,
) -> None:
    workspace, registry, _, base_revision = _services(tmp_path / "hashes.db")
    with workspace:
        created = registry.set(
            "demo",
            "main",
            "smoke",
            "application",
            expected_stdout="done\n",
            expected_revision_id=base_revision,
        )
        resolved = registry.get(
            "demo",
            "smoke",
            revision_id=created["revision_id"],
        )
        listed = registry.list("demo", revision_id=created["revision_id"])

        assert created["definition_hash"] == resolved["definition_hash"]
        assert listed[0]["definition_hash"] == created["definition_hash"]
        root = workspace._state_at_revision(created["revision_id"])[
            "@test-target/smoke"
        ]
        assert created["definition_hash"] == workspace.db.hash_value(root)


def test_verified_writes_reject_falsey_non_list_collections(tmp_path: Path) -> None:
    workspace, registry, _, base_revision = _services(tmp_path / "collections.db")
    with workspace:
        for field_name, value in (
            ("arguments", ()),
            ("arguments", ""),
            ("tags", ()),
            ("tags", ""),
        ):
            with pytest.raises(ValidationError) as raised:
                registry.set(
                    "demo",
                    "main",
                    f"invalid-{field_name}",
                    "application",
                    expected_revision_id=base_revision,
                    **{field_name: value},
                )
            assert raised.value.code == "INVALID_TEST_TARGET"
        assert workspace.branch_head("demo", "main") == base_revision


def test_bounded_page_uses_lexical_continuation_without_large_bodies(
    tmp_path: Path,
) -> None:
    workspace, registry, pages, base_revision = _services(tmp_path / "pages.db")
    with workspace:
        revision = base_revision
        for name in ("alpha", "beta", "gamma"):
            created = registry.set(
                "demo",
                "main",
                name,
                "application",
                arguments=[f"--{name}"],
                stdin="input" * 100,
                expected_stdout="output" * 100,
                expected_stderr="error" * 100,
                tags=["smoke"],
                expected_revision_id=revision,
            )
            revision = created["revision_id"]

        first = pages.page("demo", revision_id=revision, limit=2)
        second = pages.page(
            "demo",
            revision_id=revision,
            start_after_name=first["next_after_name"],
            limit=2,
        )

        assert first["format"] == TEST_TARGET_LIST_FORMAT
        assert first["revision_id"] == revision
        assert first["total_test_target_count"] == 3
        assert first["remaining_after_cursor_count"] == 3
        assert first["returned_test_target_count"] == 2
        assert first["test_targets_truncated"] is True
        assert first["next_after_name"] == "beta"
        assert [item["name"] for item in first["test_targets"]] == ["alpha", "beta"]
        assert [item["name"] for item in second["test_targets"]] == ["gamma"]
        assert second["remaining_after_cursor_count"] == 1
        assert second["test_targets_truncated"] is False
        assert second["next_after_name"] is None

        summary = first["test_targets"][0]
        assert summary["argument_count"] == 1
        assert summary["stdin_bytes"] == 500
        assert summary["expected_stdout_bytes"] == 600
        assert summary["expected_stderr_bytes"] == 500
        assert "stdin" not in summary
        assert "expected_stdout" not in summary
        assert "expected_stderr" not in summary
        assert summary["definition_hash"]
        assert summary["detail"]["arguments"]["revision_id"] == revision


def test_page_rejects_invalid_limits_and_cursors(tmp_path: Path) -> None:
    workspace, _, pages, _ = _services(tmp_path / "page-errors.db")
    with workspace:
        for limit in (0, MAX_TEST_TARGET_PAGE_SIZE + 1, True, "10"):
            with pytest.raises(ValidationError) as raised:
                pages.page("demo", limit=limit)  # type: ignore[arg-type]
            assert raised.value.code == "INVALID_TEST_TARGET_PAGE_LIMIT"

        with pytest.raises(ValidationError) as raised:
            pages.page("demo", start_after_name="bad name")
        assert raised.value.code == "INVALID_TEST_TARGET_NAME"
