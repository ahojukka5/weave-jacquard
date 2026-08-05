from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from weave_frontend.build_targets import BuildTargetRegistry
from weave_frontend.errors import ConflictError, NotFoundError, ValidationError
from weave_frontend.sexpr import make_atom, make_form
from weave_frontend.sexpr_service import SExpressionWorkspace

MAIN = """(program
  (name "main")
  (version "0.1")
  (entry main
    (params)
    (returns i32)
    (do (return (const_i32 42)))))
"""

LIBRARY = """(program
  (name "library")
  (version "0.1")
  (fn helper
    (params)
    (returns i32)
    (do (return (const_i32 7)))))
"""

LIBRARY_V2 = LIBRARY.replace('(version "0.1")', '(version "0.2")')


class RecordingBridge:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def build(
        self,
        project: str,
        document: str,
        *,
        additional_documents: list[str] | None = None,
        branch: str = "main",
        revision_id: str | None = None,
        target: str | None = None,
        evidence_profile: str | None = None,
    ) -> dict[str, Any]:
        call = {
            "project": project,
            "document": document,
            "additional_documents": additional_documents,
            "branch": branch,
            "revision_id": revision_id,
            "target": target,
            "evidence_profile": evidence_profile,
        }
        self.calls.append(call)
        return {
            "format": "weave-frontend-build-manifest-v2",
            "build_id": "a" * 32,
            "status": "succeeded",
            "revision_id": revision_id,
            "documents": [document, *(additional_documents or [])],
        }


def _workspace(tmp_path: Path) -> SExpressionWorkspace:
    workspace = SExpressionWorkspace(tmp_path / "weave.db")
    workspace.initialize("demo")
    workspace.import_program("demo", "main", "main.weave", MAIN)
    workspace.import_program("demo", "main", "library.weave", LIBRARY)
    return workspace


def test_target_is_revisioned_and_source_list_hides_metadata(tmp_path: Path) -> None:
    with _workspace(tmp_path) as workspace:
        targets = BuildTargetRegistry(workspace)
        first = targets.set("demo", "main", "app", "main.weave")
        second = targets.set(
            "demo",
            "main",
            "app",
            "main.weave",
            additional_documents=["library.weave"],
        )

        old = targets.get("demo", "app", revision_id=first["revision_id"])
        current = targets.get("demo", "app")
        listed = targets.list("demo")
        sources = targets.program_documents("demo")

    assert first["revision_id"] != second["revision_id"]
    assert old["additional_documents"] == []
    assert old["compiler_target"] == "native"
    assert old["evidence_profile"] == "none"
    assert current["additional_documents"] == ["library.weave"]
    assert current["evidence_profile"] == "none"
    assert [item["name"] for item in listed] == ["app"]
    assert sources == ["library.weave", "main.weave"]
    assert all(not name.startswith("@build-target/") for name in sources)


def test_ordinary_source_commit_preserves_target(tmp_path: Path) -> None:
    with _workspace(tmp_path) as workspace:
        targets = BuildTargetRegistry(workspace)
        target_revision = targets.set(
            "demo",
            "main",
            "app",
            "main.weave",
            additional_documents=["library.weave"],
        )["revision_id"]
        workspace.import_program(
            "demo",
            "main",
            "library.weave",
            LIBRARY_V2,
            replace=True,
        )
        after = targets.get("demo", "app")

    assert after["revision_id"] != target_revision
    assert after["document"] == "main.weave"
    assert after["additional_documents"] == ["library.weave"]


def test_merge_combines_independent_target_changes(tmp_path: Path) -> None:
    with _workspace(tmp_path) as workspace:
        targets = BuildTargetRegistry(workspace)
        targets.set("demo", "main", "app", "main.weave")
        workspace.create_branch("demo", "feature")

        targets.set(
            "demo",
            "main",
            "app",
            "main.weave",
            compiler_target="x86_64-unknown-linux-gnu",
        )
        targets.set(
            "demo",
            "feature",
            "app",
            "main.weave",
            additional_documents=["library.weave"],
        )

        workspace.merge(
            "demo",
            target_branch="main",
            source_branch="feature",
        )
        merged = targets.get("demo", "app")

    assert merged["additional_documents"] == ["library.weave"]
    assert merged["compiler_target"] == "x86_64-unknown-linux-gnu"


def test_merge_deduplicates_same_concurrent_source_addition(tmp_path: Path) -> None:
    with _workspace(tmp_path) as workspace:
        targets = BuildTargetRegistry(workspace)
        targets.set("demo", "main", "app", "main.weave")
        workspace.create_branch("demo", "feature")

        targets.set(
            "demo",
            "main",
            "app",
            "main.weave",
            additional_documents=["library.weave"],
        )
        targets.set(
            "demo",
            "feature",
            "app",
            "main.weave",
            additional_documents=["library.weave"],
        )
        workspace.merge(
            "demo",
            target_branch="main",
            source_branch="feature",
        )
        merged = targets.get("demo", "app")

    assert merged["additional_documents"] == ["library.weave"]


def test_merge_conflicts_when_same_target_field_changes_differently(
    tmp_path: Path,
) -> None:
    with _workspace(tmp_path) as workspace:
        targets = BuildTargetRegistry(workspace)
        targets.set("demo", "main", "app", "main.weave")
        workspace.create_branch("demo", "feature")

        targets.set(
            "demo",
            "main",
            "app",
            "main.weave",
            compiler_target="x86_64-unknown-linux-gnu",
        )
        targets.set(
            "demo",
            "feature",
            "app",
            "main.weave",
            compiler_target="x86_64-unknown-linux-musl",
        )

        with pytest.raises(ConflictError) as conflict:
            workspace.merge(
                "demo",
                target_branch="main",
                source_branch="feature",
            )

    assert any("@build-target/app" in item for item in conflict.value.conflicts)


def test_named_build_resolves_target_from_same_revision(tmp_path: Path) -> None:
    with _workspace(tmp_path) as workspace:
        targets = BuildTargetRegistry(workspace)
        configured = targets.set(
            "demo",
            "main",
            "app",
            "main.weave",
            additional_documents=["library.weave"],
            compiler_target="x86_64-unknown-linux-musl",
            evidence_profile="full",
        )
        bridge = RecordingBridge()
        result = targets.build(bridge, "demo", "app")

    assert bridge.calls == [
        {
            "project": "demo",
            "document": "main.weave",
            "additional_documents": ["library.weave"],
            "branch": "main",
            "revision_id": configured["revision_id"],
            "target": "x86_64-unknown-linux-musl",
            "evidence_profile": "full",
        }
    ]
    assert result["build_target"] == {
        "name": "app",
        "revision_id": configured["revision_id"],
        "document": "main.weave",
        "additional_documents": ["library.weave"],
        "compiler_target": "x86_64-unknown-linux-musl",
        "evidence_profile": "full",
    }


def test_target_validation_and_delete(tmp_path: Path) -> None:
    with _workspace(tmp_path) as workspace:
        targets = BuildTargetRegistry(workspace)
        with pytest.raises(ValidationError):
            targets.set("demo", "main", "bad target", "main.weave")
        with pytest.raises(ValidationError):
            targets.set(
                "demo",
                "main",
                "empty-target",
                "main.weave",
                compiler_target="",
            )
        with pytest.raises(ValidationError) as invalid_profile:
            targets.set(
                "demo",
                "main",
                "bad-profile",
                "main.weave",
                evidence_profile="everything",
            )
        assert invalid_profile.value.code == "INVALID_EVIDENCE_PROFILE"
        with pytest.raises(NotFoundError):
            targets.set("demo", "main", "missing", "missing.weave")
        with pytest.raises(ValidationError):
            targets.set(
                "demo",
                "main",
                "recursive",
                "main.weave",
                additional_documents=["@build-target/app"],
            )

        targets.set("demo", "main", "app", "main.weave")
        deleted = targets.delete("demo", "main", "app")
        with pytest.raises(NotFoundError):
            targets.get("demo", "app")

    assert deleted["deleted"] is True


def test_persisted_target_requires_explicit_evidence_profile() -> None:
    root = make_form("build-target")
    for head, value in (
        ("primary", "main.weave"),
        ("compiler-target", "native"),
    ):
        field = make_form(head)
        field["children"].append(make_atom("string", value))
        root["children"].append(field)

    with pytest.raises(ValidationError) as captured:
        BuildTargetRegistry._parse_tree(root, name="app")

    assert captured.value.code == "INVALID_BUILD_TARGET"
    assert "exactly one evidence-profile" in str(captured.value)
