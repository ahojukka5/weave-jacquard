from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from weave_frontend.builds import ConcurrentBuildTargetRegistry as BuildTargetRegistry
from weave_frontend.compiler import CompilerInputMixin
from weave_frontend.errors import ValidationError
from weave_frontend.revision_limits import (
    MAX_BRANCH_HISTORY_PAGE_SIZE,
    MAX_BUILD_DOCUMENTS,
)
from weave_frontend.service import RevisionWorkspace


def _append_revision(workspace: RevisionWorkspace, parent: str, index: int) -> str:
    revision = str(uuid4())
    project_id = workspace.project_id("demo")
    root_hash = workspace.db.hash_value({})
    with workspace.db.transaction() as connection:
        connection.execute(
            """INSERT INTO revisions(
                   id, project_id, parent1_id, message, author, root_hash
               ) VALUES (?, ?, ?, ?, 'test', ?)""",
            (revision, project_id, parent, f"revision {index}", root_hash),
        )
        connection.execute(
            """UPDATE branches SET head_revision_id = ?
               WHERE project_id = ? AND name = 'main'""",
            (revision, project_id),
        )
    return revision


def test_history_page_reports_presentation_truncation(tmp_path: Path) -> None:
    with RevisionWorkspace(tmp_path / "history.db") as workspace:
        _project_id, head = workspace.initialize("demo")
        for index in range(3):
            head = _append_revision(workspace, head, index)

        page = workspace.history_page("demo", limit=2)
        compatibility = workspace.list_history("demo", limit=2)

    assert page["returned_count"] == 2
    assert page["truncated"] is True
    assert page["next_revision_id"] is not None
    assert page["limits"]["page_size"] == MAX_BRANCH_HISTORY_PAGE_SIZE
    assert compatibility == page["revisions"]


@pytest.mark.parametrize("value", [True, False, 0, -1, 1.5, "10"])
def test_history_rejects_invalid_limits(tmp_path: Path, value: object) -> None:
    with RevisionWorkspace(tmp_path / "invalid-history.db") as workspace:
        workspace.initialize("demo")
        with pytest.raises(ValidationError) as captured:
            workspace.history_page("demo", limit=value)  # type: ignore[arg-type]

    assert captured.value.code == "INVALID_BRANCH_HISTORY_LIMIT"


def test_history_accepts_configured_maximum(tmp_path: Path) -> None:
    with RevisionWorkspace(tmp_path / "maximum-history.db") as workspace:
        workspace.initialize("demo")
        page = workspace.history_page(
            "demo",
            limit=MAX_BRANCH_HISTORY_PAGE_SIZE,
        )

    assert page["returned_count"] == 1
    assert page["truncated"] is False


def _document_names(count: int) -> list[str]:
    return [f"source-{index}.weave" for index in range(count)]


def test_compiler_document_limit_accepts_exact_and_rejects_plus_one() -> None:
    exact = _document_names(MAX_BUILD_DOCUMENTS)
    documents = CompilerInputMixin._ordered_documents(exact[0], exact[1:])
    assert documents == exact

    overflow = _document_names(MAX_BUILD_DOCUMENTS + 1)
    with pytest.raises(ValidationError) as captured:
        CompilerInputMixin._ordered_documents(overflow[0], overflow[1:])

    assert captured.value.code == "BUILD_DOCUMENT_LIMIT_EXCEEDED"


def test_production_target_document_limit_matches_compiler_boundary() -> None:
    exact = _document_names(MAX_BUILD_DOCUMENTS)
    documents = BuildTargetRegistry._validate_document_set(exact[0], exact[1:])
    assert documents == exact

    overflow = _document_names(MAX_BUILD_DOCUMENTS + 1)
    with pytest.raises(ValidationError) as captured:
        BuildTargetRegistry._validate_document_set(overflow[0], overflow[1:])

    assert captured.value.code == "BUILD_DOCUMENT_LIMIT_EXCEEDED"
