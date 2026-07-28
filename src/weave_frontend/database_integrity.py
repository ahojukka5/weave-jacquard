"""Read-only integrity inspection for Jacquard SQLite databases."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .errors import ValidationError

DATABASE_INTEGRITY_FORMAT = "weave-database-integrity-v1"
MAX_INTEGRITY_EXAMPLES = 20
_RELATIONAL_TABLES = (
    "projects",
    "revisions",
    "branches",
    "operations",
    "documents",
    "revision_documents",
)
_RELATIONAL_INVARIANTS = (
    "foreign_keys",
    "revision_parent_project_ownership",
    "branch_project_ownership",
    "branch_head_project_ownership",
    "operation_sequence_uniqueness",
)
_REQUIRED_TABLES = (
    *_RELATIONAL_TABLES,
    "module_snapshots_compressed",
)


def inspect_database(path: str | Path) -> dict[str, Any]:
    """Inspect one existing database without running migrations or writing bytes."""

    database_path = Path(path).expanduser()
    if not database_path.is_file():
        raise ValidationError(
            "DATABASE_NOT_FOUND",
            f"database file does not exist: {database_path}",
        )

    uri = database_path.resolve().as_uri() + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise ValidationError(
            "DATABASE_OPEN_FAILED",
            f"cannot open database read-only: {exc}",
        ) from exc
    connection.row_factory = sqlite3.Row
    try:
        try:
            return inspect_connection(connection, path=database_path.resolve())
        except sqlite3.DatabaseError as exc:
            raise ValidationError(
                "DATABASE_INSPECTION_FAILED",
                f"database integrity inspection failed: {exc}",
            ) from exc
    finally:
        connection.close()


def inspect_connection(
    connection: sqlite3.Connection,
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    """Return bounded integrity evidence for one open SQLite connection."""

    current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    placeholders = ",".join("?" for _ in _REQUIRED_TABLES)
    object_rows = connection.execute(
        f"SELECT name, type FROM sqlite_master WHERE name IN ({placeholders})",
        _REQUIRED_TABLES,
    )
    objects = {str(row[0]): str(row[1]) for row in object_rows}
    issues: list[dict[str, Any]] = []
    checked_invariants = ["required_tables", "sqlite_quick_check"]
    skipped_invariants: list[str] = []

    missing_tables = [name for name in _REQUIRED_TABLES if objects.get(name) != "table"]
    if missing_tables:
        issues.append(
            {
                "code": "MISSING_DATABASE_TABLES",
                "count": len(missing_tables),
                "examples": missing_tables[:MAX_INTEGRITY_EXAMPLES],
                "examples_truncated": len(missing_tables) > MAX_INTEGRITY_EXAMPLES,
            }
        )

    quick_issue = _issue_from_cursor(
        "SQLITE_QUICK_CHECK_FAILED",
        connection.execute("PRAGMA quick_check"),
        lambda row: None if str(row[0]) == "ok" else str(row[0]),
    )
    if quick_issue is not None:
        issues.append(quick_issue)

    relational_core_present = all(objects.get(name) == "table" for name in _RELATIONAL_TABLES)
    if relational_core_present:
        checked_invariants.extend(_RELATIONAL_INVARIANTS)
        foreign_key_issue = _issue_from_cursor(
            "FOREIGN_KEY_VIOLATIONS",
            connection.execute("PRAGMA foreign_key_check"),
            lambda row: {
                "table": str(row[0]),
                "rowid": row[1],
                "parent": str(row[2]),
                "foreign_key_index": int(row[3]),
            },
        )
        if foreign_key_issue is not None:
            issues.append(foreign_key_issue)

        issues.extend(_project_link_issues(connection))
        issues.extend(_operation_sequence_issues(connection))
    else:
        skipped_invariants.extend(_RELATIONAL_INVARIANTS)

    return {
        "format": DATABASE_INTEGRITY_FORMAT,
        "path": str(path) if path is not None else None,
        "schema_version": current_version,
        "valid": not issues,
        "issue_count": len(issues),
        "issues": issues,
        "checked_invariants": checked_invariants,
        "skipped_invariants": skipped_invariants,
    }


def require_migration_integrity(connection: sqlite3.Connection) -> None:
    """Reject legacy data that cannot safely receive schema-v3 constraints."""

    report = inspect_connection(connection)
    blocking: list[dict[str, Any]] = []
    for issue in report["issues"]:
        if issue["code"] != "MISSING_DATABASE_TABLES":
            blocking.append(issue)
            continue
        missing = set(issue["examples"])
        legacy_snapshot = connection.execute(
            """SELECT 1 FROM sqlite_master
               WHERE type = 'table' AND name = 'module_snapshots'"""
        ).fetchone()
        allowed = {"module_snapshots_compressed"} if legacy_snapshot is not None else set()
        if missing - allowed:
            blocking.append(issue)

    if blocking:
        codes = ", ".join(str(issue["code"]) for issue in blocking)
        raise RuntimeError(
            "database integrity check failed before schema v3 migration: " + codes
        )


def _project_link_issues(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    parent1 = _query_examples(
        connection,
        """SELECT child.id AS revision_id,
                  child.project_id AS child_project_id,
                  child.parent1_id AS parent_revision_id,
                  parent.project_id AS parent_project_id
           FROM revisions child
           JOIN revisions parent ON parent.id = child.parent1_id
           WHERE child.project_id <> parent.project_id
           ORDER BY child.id""",
    )
    if parent1["count"]:
        issues.append(_issue_from_query("CROSS_PROJECT_PARENT1", parent1))

    parent2 = _query_examples(
        connection,
        """SELECT child.id AS revision_id,
                  child.project_id AS child_project_id,
                  child.parent2_id AS parent_revision_id,
                  parent.project_id AS parent_project_id
           FROM revisions child
           JOIN revisions parent ON parent.id = child.parent2_id
           WHERE child.project_id <> parent.project_id
           ORDER BY child.id""",
    )
    if parent2["count"]:
        issues.append(_issue_from_query("CROSS_PROJECT_PARENT2", parent2))

    missing_projects = _query_examples(
        connection,
        """SELECT branch.project_id, branch.name, branch.head_revision_id
           FROM branches branch
           LEFT JOIN projects project ON project.id = branch.project_id
           WHERE project.id IS NULL
           ORDER BY branch.project_id, branch.name""",
    )
    if missing_projects["count"]:
        issues.append(_issue_from_query("BRANCH_PROJECT_NOT_FOUND", missing_projects))

    cross_project_heads = _query_examples(
        connection,
        """SELECT branch.project_id AS branch_project_id,
                  branch.name,
                  branch.head_revision_id,
                  revision.project_id AS revision_project_id
           FROM branches branch
           JOIN revisions revision ON revision.id = branch.head_revision_id
           WHERE branch.project_id <> revision.project_id
           ORDER BY branch.project_id, branch.name""",
    )
    if cross_project_heads["count"]:
        issues.append(
            _issue_from_query("CROSS_PROJECT_BRANCH_HEAD", cross_project_heads)
        )

    return issues


def _operation_sequence_issues(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    duplicates = _query_examples(
        connection,
        """SELECT revision_id, sequence_number, COUNT(*) AS duplicate_count
           FROM operations
           GROUP BY revision_id, sequence_number
           HAVING COUNT(*) > 1
           ORDER BY revision_id, sequence_number""",
    )
    if not duplicates["count"]:
        return []
    return [_issue_from_query("DUPLICATE_OPERATION_SEQUENCE", duplicates)]


def _query_examples(
    connection: sqlite3.Connection,
    query: str,
) -> dict[str, Any]:
    count_query = f"SELECT COUNT(*) FROM ({query})"
    count = int(connection.execute(count_query).fetchone()[0])
    cursor = connection.execute(f"{query} LIMIT ?", (MAX_INTEGRITY_EXAMPLES,))
    columns = [str(item[0]) for item in cursor.description or ()]
    rows = [
        {column: row[index] for index, column in enumerate(columns)}
        for row in cursor
    ]
    return {
        "count": count,
        "examples": rows,
        "examples_truncated": count > MAX_INTEGRITY_EXAMPLES,
    }


def _issue_from_cursor(
    code: str,
    cursor: sqlite3.Cursor,
    transform: Callable[[Any], Any | None],
) -> dict[str, Any] | None:
    count = 0
    examples: list[Any] = []
    for row in cursor:
        value = transform(row)
        if value is None:
            continue
        count += 1
        if len(examples) < MAX_INTEGRITY_EXAMPLES:
            examples.append(value)
    if count == 0:
        return None
    return {
        "code": code,
        "count": count,
        "examples": examples,
        "examples_truncated": count > MAX_INTEGRITY_EXAMPLES,
    }


def _issue_from_query(code: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": code,
        "count": result["count"],
        "examples": result["examples"],
        "examples_truncated": result["examples_truncated"],
    }


__all__ = [
    "DATABASE_INTEGRITY_FORMAT",
    "inspect_connection",
    "inspect_database",
    "require_migration_integrity",
]
