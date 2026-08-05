from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from weave_frontend import SExpressionWorkspace
from weave_frontend.database import Database
from weave_frontend.database_integrity import inspect_database
from weave_frontend.errors import ArtifactIntegrityError, ValidationError
from weave_frontend.snapshot_codec import (
    canonical_json,
    compress_snapshot_json,
    hash_value,
)
from weave_frontend.verified_database_backup import DatabaseBackupService


def _database_with_program(path: Path) -> tuple[str, str]:
    with SExpressionWorkspace(path) as workspace:
        workspace.initialize("demo")
        result = workspace.import_program(
            "demo",
            "main",
            "main.weave",
            '(program (name "demo") (version "0.1"))',
        )
        return result["revision_id"], workspace.render(
            "demo",
            "main",
            "main.weave",
        )


def _issue_codes(path: Path) -> set[str]:
    return {issue["code"] for issue in inspect_database(path)["issues"]}


def test_ast_hash_mismatch_is_reported_and_normal_reads_fail(tmp_path: Path) -> None:
    path = tmp_path / "ast-hash.db"
    revision_id, _source = _database_with_program(path)

    connection = sqlite3.connect(path)
    connection.execute(
        """UPDATE module_snapshots_compressed
           SET ast_hash = ?
           WHERE revision_id = ? AND qualified_name = 'main.weave'""",
        ("0" * 64, revision_id),
    )
    connection.commit()
    connection.close()

    assert "SNAPSHOT_AST_HASH_MISMATCH" in _issue_codes(path)
    with SExpressionWorkspace(path) as workspace, pytest.raises(ValidationError) as captured:
        workspace.render("demo", "main", "main.weave")
    assert captured.value.code == "CORRUPT_REVISION_STATE"
    assert "SNAPSHOT_AST_HASH_MISMATCH" in captured.value.message


def test_integrity_retains_every_admitted_snapshot_error(tmp_path: Path) -> None:
    path = tmp_path / "all-snapshot-errors.db"
    with SExpressionWorkspace(path) as workspace:
        workspace.initialize("demo")
        workspace.import_program(
            "demo",
            "main",
            "a.weave",
            '(program (name "a") (version "0.1"))',
        )
        result = workspace.import_program(
            "demo",
            "main",
            "b.weave",
            '(program (name "b") (version "0.1"))',
        )
    revision_id = result["revision_id"]

    connection = sqlite3.connect(path)
    connection.execute(
        """UPDATE module_snapshots_compressed
           SET ast_hash = ? WHERE revision_id = ?""",
        ("0" * 64, revision_id),
    )
    connection.commit()
    connection.close()

    report = inspect_database(path)
    issue = next(item for item in report["issues"] if item["code"] == "SNAPSHOT_AST_HASH_MISMATCH")
    assert issue["count"] == 2
    assert [item["qualified_name"] for item in issue["examples"]] == [
        "a.weave",
        "b.weave",
    ]
    assert issue["examples_truncated"] is False


def test_revision_root_hash_mismatch_is_reported_and_reads_fail(tmp_path: Path) -> None:
    path = tmp_path / "root-hash.db"
    revision_id, _source = _database_with_program(path)

    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE revisions SET root_hash = ? WHERE id = ?",
        ("0" * 64, revision_id),
    )
    connection.commit()
    connection.close()

    assert "REVISION_ROOT_HASH_MISMATCH" in _issue_codes(path)
    with SExpressionWorkspace(path) as workspace, pytest.raises(ValidationError) as captured:
        workspace.render("demo", "main", "main.weave")
    assert captured.value.code == "CORRUPT_REVISION_STATE"
    assert "REVISION_ROOT_HASH_MISMATCH" in captured.value.message


def test_structurally_invalid_snapshot_is_rejected_even_with_matching_hashes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "invalid-tree.db"
    revision_id, _source = _database_with_program(path)
    invalid = {"not": "a tree"}

    connection = sqlite3.connect(path)
    connection.execute(
        """UPDATE module_snapshots_compressed
           SET ast_blob = ?, ast_hash = ?
           WHERE revision_id = ? AND qualified_name = 'main.weave'""",
        (
            compress_snapshot_json(canonical_json(invalid)),
            hash_value(invalid),
            revision_id,
        ),
    )
    connection.execute(
        "UPDATE revisions SET root_hash = ? WHERE id = ?",
        (hash_value({"main.weave": invalid}), revision_id),
    )
    connection.commit()
    connection.close()

    assert "SNAPSHOT_TREE_INVALID" in _issue_codes(path)


def test_operation_payload_and_sequence_integrity_are_verified(tmp_path: Path) -> None:
    path = tmp_path / "operations.db"
    revision_id, _source = _database_with_program(path)

    connection = sqlite3.connect(path)
    connection.execute(
        """UPDATE operations
           SET sequence_number = 2,
               payload_json = '{ "document": "main.weave" }'
           WHERE revision_id = ?""",
        (revision_id,),
    )
    connection.commit()
    connection.close()

    assert _issue_codes(path) >= {
        "OPERATION_SEQUENCE_NOT_CONTIGUOUS",
        "OPERATION_PAYLOAD_NOT_CANONICAL",
    }

    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE operations SET payload_json = '{' WHERE revision_id = ?",
        (revision_id,),
    )
    connection.commit()
    connection.close()
    assert "OPERATION_PAYLOAD_JSON_INVALID" in _issue_codes(path)


def test_context_document_hash_mismatch_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "context.db"
    with SExpressionWorkspace(path) as workspace:
        workspace.initialize("demo")
        workspace.add_context(
            "demo",
            "main",
            scope_kind="project",
            scope_name="demo",
            title="Design",
            body="Trusted context",
        )

    connection = sqlite3.connect(path)
    connection.execute("UPDATE documents SET body = 'tampered'")
    connection.commit()
    connection.close()

    assert "CONTEXT_DOCUMENT_HASH_MISMATCH" in _issue_codes(path)


def test_revision_parent_cycle_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "cycle.db"
    child_revision, _source = _database_with_program(path)

    connection = sqlite3.connect(path)
    root_revision = connection.execute(
        "SELECT parent1_id FROM revisions WHERE id = ?",
        (child_revision,),
    ).fetchone()[0]
    connection.execute(
        "UPDATE revisions SET parent1_id = ? WHERE id = ?",
        (child_revision, root_revision),
    )
    connection.commit()
    connection.close()

    report = inspect_database(path)
    issue = next(issue for issue in report["issues"] if issue["code"] == "REVISION_PARENT_CYCLE")
    assert issue["count"] == 1
    assert issue["examples"][0]["revision_count"] == 2
    assert issue["examples"][0]["revision_ids_truncated"] is False
    assert sorted(issue["examples"][0]["revision_ids"]) == sorted([root_revision, child_revision])


def test_backup_creation_rejects_semantically_corrupt_source(tmp_path: Path) -> None:
    path = tmp_path / "source.db"
    revision_id, _source = _database_with_program(path)
    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE revisions SET root_hash = ? WHERE id = ?",
        ("0" * 64, revision_id),
    )
    connection.commit()
    connection.close()

    with Database(path) as database:
        service = DatabaseBackupService(
            database,
            backup_root=tmp_path / "backups",
        )
        with pytest.raises(ValidationError) as captured:
            service.create()

    assert captured.value.code == "DATABASE_BACKUP_INTEGRITY_FAILED"
    assert list((tmp_path / "backups").iterdir()) == []


def test_retained_backup_rejects_semantic_corruption_with_consistent_hashes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "source.db"
    _revision_id, _source = _database_with_program(path)
    backup_root = tmp_path / "backups"
    with Database(path) as database:
        service = DatabaseBackupService(database, backup_root=backup_root)
        backup = service.create()

    old_directory = backup_root / backup["backup_id"]
    database_path = old_directory / "database.sqlite3"
    connection = sqlite3.connect(database_path)
    connection.execute("UPDATE revisions SET root_hash = ?", ("0" * 64,))
    connection.commit()
    connection.close()

    manifest_path = old_directory / "backup-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    identity = service._database_file_identity(database_path)
    database_identity = service._database_identity(database_path)
    key = service._backup_key(
        source=manifest["source"],
        backup_database=database_identity,
        artifact_identity=identity,
    )
    new_id = service._hash_json(key)
    manifest.update(
        {
            "backup_id": new_id,
            "backup_database": database_identity,
            "artifact_bytes": {"database": identity["bytes"]},
            "artifact_sha256": {"database": identity["sha256"]},
            "backup_key": key,
        }
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    new_directory = backup_root / new_id
    old_directory.rename(new_directory)

    offline = DatabaseBackupService(None, backup_root=backup_root)
    with pytest.raises(ArtifactIntegrityError, match="integrity evidence"):
        offline.get(new_id)
    with pytest.raises(ArtifactIntegrityError):
        offline.restore(new_id, tmp_path / "restored.db")


def test_semantic_integrity_report_includes_complete_metrics_and_limits(
    tmp_path: Path,
) -> None:
    path = tmp_path / "metrics.db"
    _database_with_program(path)

    report = inspect_database(path)

    assert report["valid"] is True
    assert report["semantic_metrics"]["revisions_checked"] == 2
    assert report["semantic_metrics"]["modules_checked"] == 1
    assert report["semantic_metrics"]["decoded_snapshot_bytes"] > 0
    assert report["semantic_metrics"]["operations_checked"] == 1
    assert report["limits"]["snapshot_compressed_bytes"] > 0
    assert report["limits"]["revision_modules"] > 0
