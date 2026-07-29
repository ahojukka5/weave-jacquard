from __future__ import annotations

import sqlite3
from argparse import Namespace
from pathlib import Path

import pytest

from weave_frontend import SExpressionWorkspace
from weave_frontend.build_cli import _execute
from weave_frontend.errors import ValidationError


def test_build_cli_reads_revision_state_through_semantic_verifier(
    tmp_path: Path,
) -> None:
    path = tmp_path / "workspace.db"
    with SExpressionWorkspace(path) as workspace:
        workspace.initialize("demo")
        result = workspace.import_program(
            "demo",
            "main",
            "main.weave",
            '(program (name "demo") (version "0.1"))',
        )

    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE revisions SET root_hash = ? WHERE id = ?",
        ("0" * 64, result["revision_id"]),
    )
    connection.commit()
    connection.close()

    args = Namespace(
        command="source-list",
        db=path,
        weavec=None,
        project="demo",
        branch="main",
        revision=None,
    )
    with pytest.raises(ValidationError) as captured:
        _execute(args)

    assert captured.value.code == "CORRUPT_REVISION_STATE"
    assert "REVISION_ROOT_HASH_MISMATCH" in captured.value.message
