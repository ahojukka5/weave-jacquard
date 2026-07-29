"""Read-only relational and semantic integrity inspection for Jacquard databases."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .errors import ValidationError
from .snapshot_codec import (
    MAX_QUALIFIED_NAME_BYTES,
    MAX_REVISION_DECODED_BYTES,
    MAX_REVISION_MODULES,
    MAX_SNAPSHOT_COMPRESSED_BYTES,
    MAX_SNAPSHOT_DECOMPRESSED_BYTES,
    canonical_json,
    hash_value,
    inspect_revision_state,
)

DATABASE_INTEGRITY_FORMAT = "weave-database-integrity-v1"
DATABASE_SEMANTIC_INTEGRITY_CONTRACT = "weave-database-semantic-integrity-v1"
MAX_INTEGRITY_EXAMPLES = 20
MAX_INTEGRITY_CYCLE_REVISIONS = 64
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
_SEMANTIC_INVARIANTS = (
    "bounded_snapshot_decoding",
    "snapshot_tree_structure",
    "snapshot_ast_hashes",
    "revision_root_hashes",
    "operation_sequence_contiguity",
    "operation_payload_json",
    "operation_payload_canonical_json",
    "context_document_hashes",
    "revision_parent_acyclicity",
)
_REQUIRED_TABLES = (
    *_RELATIONAL_TABLES,
    "module_snapshots_compressed",
)


class _Issues:
    """Retain exact issue counts with one bounded deterministic example prefix."""

    def __init__(self) -> None:
        self._order: list[str] = []
        self._values: dict[str, dict[str, Any]] = {}

    def _entry(self, code: str) -> dict[str, Any]:
        issue = self._values.get(code)
        if issue is None:
            issue = {"code": code, "count": 0, "examples": []}
            self._values[code] = issue
            self._order.append(code)
        return issue

    def add(self, code: str, example: Any) -> None:
        issue = self._entry(code)
        issue["count"] += 1
        if len(issue["examples"]) < MAX_INTEGRITY_EXAMPLES:
            issue["examples"].append(example)

    def append(self, issue: dict[str, Any]) -> None:
        code = str(issue["code"])
        target = self._entry(code)
        count = int(issue["count"])
        examples = list(issue.get("examples", []))
        target["count"] += count
        available = MAX_INTEGRITY_EXAMPLES - len(target["examples"])
        if available > 0:
            target["examples"].extend(examples[:available])

    def render(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for code in self._order:
            issue = self._values[code]
            result.append(
                {
                    **issue,
                    "examples_truncated": issue["count"] > len(issue["examples"]),
                }
            )
        return result


def inspect_database(path: str | Path) -> dict[str, Any]:
    """Inspect one existing database without running migrations or writing bytes."""

    database_path = Path(path).expanduser()
    if not database_path.is_file():
        raise ValidationError(
            "DATABASE_NOT_FOUND",
            "database file does not exist",
        )

    uri = database_path.resolve().as_uri() + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise ValidationError(
            "DATABASE_OPEN_FAILED",
            "cannot open database read-only",
        ) from exc
    connection.row_factory = sqlite3.Row
    try:
        try:
            return inspect_connection(connection, path=database_path.resolve())
        except sqlite3.DatabaseError as exc:
            raise ValidationError(
                "DATABASE_INSPECTION_FAILED",
                "database integrity inspection failed",
            ) from exc
    finally:
        connection.close()


def inspect_connection(
    connection: sqlite3.Connection,
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    """Return bounded relational and semantic integrity evidence."""

    current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    names = (*_REQUIRED_TABLES, "module_snapshots")
    placeholders = ",".join("?" for _ in names)
    object_rows = connection.execute(
        f"SELECT name, type FROM sqlite_master WHERE name IN ({placeholders})",
        names,
    )
    objects = {str(row[0]): str(row[1]) for row in object_rows}
    issues = _Issues()
    checked_invariants = ["required_tables", "sqlite_quick_check"]
    skipped_invariants: list[str] = []

    missing_tables = [
        name for name in _REQUIRED_TABLES if objects.get(name) != "table"
    ]
    if missing_tables:
        issues.append(
            {
                "code": "MISSING_DATABASE_TABLES",
                "count": len(missing_tables),
                "examples": missing_tables[:MAX_INTEGRITY_EXAMPLES],
            }
        )

    quick_issue = _issue_from_cursor(
        "SQLITE_QUICK_CHECK_FAILED",
        connection.execute("PRAGMA quick_check"),
        lambda row: None if str(row[0]) == "ok" else str(row[0]),
    )
    if quick_issue is not None:
        issues.append(quick_issue)

    relational_core_present = all(
        objects.get(name) == "table" for name in _RELATIONAL_TABLES
    )
    semantic_metrics = {
        "revisions_checked": 0,
        "modules_checked": 0,
        "decoded_snapshot_bytes": 0,
        "operations_checked": 0,
        "documents_checked": 0,
    }
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

        for issue in _project_link_issues(connection):
            issues.append(issue)
        for issue in _operation_sequence_uniqueness_issues(connection):
            issues.append(issue)

        snapshot_mode = _snapshot_mode(objects)
        if snapshot_mode is None:
            skipped_invariants.extend(_SEMANTIC_INVARIANTS)
        else:
            checked_invariants.extend(_SEMANTIC_INVARIANTS)
            _inspect_revision_states(
                connection,
                issues,
                semantic_metrics,
                legacy=snapshot_mode == "legacy",
            )
            _inspect_operations(connection, issues, semantic_metrics)
            _inspect_documents(connection, issues, semantic_metrics)
            _inspect_parent_cycles(connection, issues)
    else:
        skipped_invariants.extend((*_RELATIONAL_INVARIANTS, *_SEMANTIC_INVARIANTS))

    rendered_issues = issues.render()
    return {
        "format": DATABASE_INTEGRITY_FORMAT,
        "semantic_contract": DATABASE_SEMANTIC_INTEGRITY_CONTRACT,
        "path": str(path) if path is not None else None,
        "schema_version": current_version,
        "valid": not rendered_issues,
        "issue_count": len(rendered_issues),
        "issues": rendered_issues,
        "checked_invariants": checked_invariants,
        "skipped_invariants": skipped_invariants,
        "semantic_metrics": semantic_metrics,
        "limits": {
            "integrity_examples": MAX_INTEGRITY_EXAMPLES,
            "integrity_cycle_revisions": MAX_INTEGRITY_CYCLE_REVISIONS,
            "snapshot_compressed_bytes": MAX_SNAPSHOT_COMPRESSED_BYTES,
            "snapshot_decompressed_bytes": MAX_SNAPSHOT_DECOMPRESSED_BYTES,
            "revision_modules": MAX_REVISION_MODULES,
            "revision_decoded_bytes": MAX_REVISION_DECODED_BYTES,
            "qualified_name_bytes": MAX_QUALIFIED_NAME_BYTES,
        },
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
        allowed = (
            {"module_snapshots_compressed"}
            if legacy_snapshot is not None
            else set()
        )
        if missing - allowed:
            blocking.append(issue)

    if blocking:
        codes = ", ".join(str(issue["code"]) for issue in blocking)
        raise RuntimeError(
            "database integrity check failed before schema v3 migration: " + codes
        )


def _snapshot_mode(objects: dict[str, str]) -> str | None:
    if objects.get("module_snapshots_compressed") == "table":
        return "compressed"
    if objects.get("module_snapshots") == "table":
        return "legacy"
    return None


def _inspect_revision_states(
    connection: sqlite3.Connection,
    issues: _Issues,
    metrics: dict[str, int],
    *,
    legacy: bool,
) -> None:
    for row in connection.execute(
        "SELECT id, root_hash FROM revisions ORDER BY id"
    ):
        revision_id = str(row[0])
        metrics["revisions_checked"] += 1
        inspection = inspect_revision_state(
            connection,
            revision_id,
            expected_root_hash=row[1],
            legacy=legacy,
        )
        metrics["modules_checked"] += inspection.modules_scanned
        metrics["decoded_snapshot_bytes"] += inspection.decoded_bytes
        for error in inspection.errors:
            issues.add(error.code, error.example())


def _inspect_operations(
    connection: sqlite3.Connection,
    issues: _Issues,
    metrics: dict[str, int],
) -> None:
    previous_revision: str | None = None
    expected_sequence = 0
    cursor = connection.execute(
        """SELECT id, revision_id, sequence_number, payload_json
           FROM operations
           ORDER BY revision_id, sequence_number, id"""
    )
    for row in cursor:
        operation_id = str(row[0])
        revision_id = str(row[1])
        sequence = row[2]
        metrics["operations_checked"] += 1
        if revision_id != previous_revision:
            previous_revision = revision_id
            expected_sequence = 0
        if isinstance(sequence, bool) or not isinstance(sequence, int):
            issues.add(
                "OPERATION_SEQUENCE_INVALID",
                {"operation_id": operation_id, "revision_id": revision_id},
            )
        elif sequence != expected_sequence:
            issues.add(
                "OPERATION_SEQUENCE_NOT_CONTIGUOUS",
                {
                    "operation_id": operation_id,
                    "revision_id": revision_id,
                    "expected": expected_sequence,
                    "observed": sequence,
                },
            )
            expected_sequence = sequence + 1
        else:
            expected_sequence += 1

        payload_text = row[3]
        if not isinstance(payload_text, str):
            issues.add(
                "OPERATION_PAYLOAD_JSON_INVALID",
                {"operation_id": operation_id, "revision_id": revision_id},
            )
            continue
        try:
            payload = json.loads(payload_text)
        except (json.JSONDecodeError, RecursionError):
            issues.add(
                "OPERATION_PAYLOAD_JSON_INVALID",
                {"operation_id": operation_id, "revision_id": revision_id},
            )
            continue
        if not isinstance(payload, dict):
            issues.add(
                "OPERATION_PAYLOAD_NOT_OBJECT",
                {"operation_id": operation_id, "revision_id": revision_id},
            )
            continue
        try:
            canonical = canonical_json(payload)
            canonical.encode("utf-8")
        except (TypeError, ValueError, RecursionError, UnicodeEncodeError):
            issues.add(
                "OPERATION_PAYLOAD_JSON_INVALID",
                {"operation_id": operation_id, "revision_id": revision_id},
            )
            continue
        if canonical != payload_text:
            issues.add(
                "OPERATION_PAYLOAD_NOT_CANONICAL",
                {"operation_id": operation_id, "revision_id": revision_id},
            )


def _inspect_documents(
    connection: sqlite3.Connection,
    issues: _Issues,
    metrics: dict[str, int],
) -> None:
    cursor = connection.execute(
        """SELECT id, scope_kind, scope_name, title, body, content_hash
           FROM documents ORDER BY id"""
    )
    for row in cursor:
        document_id = str(row[0])
        metrics["documents_checked"] += 1
        try:
            observed = hash_value(
                {
                    "scope_kind": row[1],
                    "scope_name": row[2],
                    "title": row[3],
                    "body": row[4],
                }
            )
        except (TypeError, ValueError, RecursionError, UnicodeEncodeError):
            issues.add(
                "CONTEXT_DOCUMENT_VALUE_INVALID",
                {"document_id": document_id},
            )
            continue
        if observed != row[5]:
            issues.add(
                "CONTEXT_DOCUMENT_HASH_MISMATCH",
                {"document_id": document_id},
            )


def _inspect_parent_cycles(
    connection: sqlite3.Connection,
    issues: _Issues,
) -> None:
    parents = {
        str(row[0]): tuple(
            str(parent) for parent in (row[1], row[2]) if parent is not None
        )
        for row in connection.execute(
            "SELECT id, parent1_id, parent2_id FROM revisions ORDER BY id"
        )
    }
    color: dict[str, int] = {}
    reported: set[tuple[str, ...]] = set()
    for start in sorted(parents):
        if color.get(start, 0) != 0:
            continue
        stack: list[tuple[str, int]] = [(start, 0)]
        path: list[str] = []
        positions: dict[str, int] = {}
        while stack:
            node, parent_index = stack[-1]
            if color.get(node, 0) == 0:
                color[node] = 1
                positions[node] = len(path)
                path.append(node)
            node_parents = parents.get(node, ())
            if parent_index >= len(node_parents):
                stack.pop()
                color[node] = 2
                positions.pop(node, None)
                if path and path[-1] == node:
                    path.pop()
                continue
            parent = node_parents[parent_index]
            stack[-1] = (node, parent_index + 1)
            parent_color = color.get(parent, 0)
            if parent_color == 0:
                stack.append((parent, 0))
                continue
            if parent_color == 1:
                cycle_start = positions[parent]
                cycle = tuple(sorted(path[cycle_start:]))
                if cycle not in reported:
                    reported.add(cycle)
                    retained = cycle[:MAX_INTEGRITY_CYCLE_REVISIONS]
                    issues.add(
                        "REVISION_PARENT_CYCLE",
                        {
                            "revision_ids": list(retained),
                            "revision_count": len(cycle),
                            "revision_ids_truncated": len(cycle) > len(retained),
                        },
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


def _operation_sequence_uniqueness_issues(
    connection: sqlite3.Connection,
) -> list[dict[str, Any]]:
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
    "DATABASE_SEMANTIC_INTEGRITY_CONTRACT",
    "MAX_INTEGRITY_CYCLE_REVISIONS",
    "MAX_INTEGRITY_EXAMPLES",
    "inspect_connection",
    "inspect_database",
    "require_migration_integrity",
]
