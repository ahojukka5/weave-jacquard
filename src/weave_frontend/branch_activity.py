"""Paginated branch history and measured workflow activity."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any

from .errors import NotFoundError, ValidationError
from .revision_limits import (
    MAX_BRANCH_ACTIVITY_REVISIONS,
    MAX_BRANCH_HISTORY_PAGE_SIZE,
    MAX_OPERATION_PAGE_SIZE,
    require_bounded_int,
    require_nonnegative_int,
)
from .service import RevisionWorkspace

MAX_HISTORY_PAGE_SIZE = MAX_BRANCH_HISTORY_PAGE_SIZE


class BranchActivityService:
    """Read bounded branch histories and summarize admitted edit activity."""

    def __init__(self, workspace: RevisionWorkspace) -> None:
        self.workspace = workspace

    def history_page(
        self,
        project: str,
        branch: str = "main",
        *,
        start_revision_id: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        effective_limit = require_bounded_int(
            limit,
            code="INVALID_HISTORY_LIMIT",
            name="limit",
            minimum=1,
            maximum=MAX_HISTORY_PAGE_SIZE,
        )
        project_id = self.workspace.project_id(project)
        branch_head = self.workspace.branch_head(project, branch)
        start = start_revision_id or branch_head
        if not self._is_first_parent_reachable(branch_head, start):
            raise ValidationError(
                "REVISION_NOT_REACHABLE",
                f"revision {start!r} is not in the first-parent history of {branch!r}",
            )

        rows = self.workspace.db.connection.execute(
            """WITH RECURSIVE history(
                       id, parent1_id, parent2_id, message, author, root_hash,
                       created_at, depth
                   ) AS (
                       SELECT id, parent1_id, parent2_id, message, author,
                              root_hash, created_at, 0
                       FROM revisions
                       WHERE id = ? AND project_id = ?
                       UNION ALL
                       SELECT r.id, r.parent1_id, r.parent2_id, r.message,
                              r.author, r.root_hash, r.created_at, h.depth + 1
                       FROM revisions r
                       JOIN history h ON r.id = h.parent1_id
                       WHERE r.project_id = ? AND h.depth < ?
                   )
                   SELECT id, parent1_id, parent2_id, message, author, root_hash,
                          created_at, depth
                   FROM history
                   ORDER BY depth
                   LIMIT ?""",
            (start, project_id, project_id, effective_limit, effective_limit + 1),
        ).fetchall()
        if not rows:
            raise NotFoundError(f"revision {start!r} not found")

        page_rows = rows[:effective_limit]
        operation_map = self._operations_for_revisions(
            [str(row["id"]) for row in page_rows]
        )
        revisions: list[dict[str, Any]] = []
        for row in page_rows:
            revision_id = str(row["id"])
            kinds = operation_map.get(revision_id, [])
            revisions.append(
                {
                    "id": revision_id,
                    "parent1_id": row["parent1_id"],
                    "parent2_id": row["parent2_id"],
                    "message": row["message"],
                    "author": row["author"],
                    "root_hash": row["root_hash"],
                    "created_at": row["created_at"],
                    "depth_from_page_start": int(row["depth"]),
                    "operation_count": len(kinds),
                    "operation_kinds": kinds,
                }
            )

        next_revision_id = (
            str(rows[effective_limit]["id"])
            if len(rows) > effective_limit
            else None
        )
        truncated = next_revision_id is not None
        return {
            "project": project,
            "branch": branch,
            "branch_head_revision_id": branch_head,
            "start_revision_id": start,
            "limit": effective_limit,
            "returned_count": len(revisions),
            "has_more": truncated,
            "truncated": truncated,
            "next_revision_id": next_revision_id,
            "limits": {
                "maximum_page_size": MAX_HISTORY_PAGE_SIZE,
                "maximum_reachability_scan": MAX_BRANCH_ACTIVITY_REVISIONS,
            },
            "revisions": revisions,
        }

    def revision_operations_page(
        self,
        project: str,
        revision_id: str,
        *,
        start_sequence_number: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Read immutable operation audit rows in sequence-number order."""

        effective_limit = require_bounded_int(
            limit,
            code="INVALID_OPERATION_LIMIT",
            name="limit",
            minimum=1,
            maximum=MAX_OPERATION_PAGE_SIZE,
        )
        effective_start = require_nonnegative_int(
            start_sequence_number,
            code="INVALID_OPERATION_SEQUENCE",
            name="start_sequence_number",
        )

        project_id = self.workspace.project_id(project)
        revision = self.workspace.db.connection.execute(
            """SELECT id, parent1_id, parent2_id, message, author, root_hash,
                      created_at
               FROM revisions
               WHERE id = ? AND project_id = ?""",
            (revision_id, project_id),
        ).fetchone()
        if revision is None:
            raise NotFoundError(
                f"revision {revision_id!r} not found in project {project!r}"
            )

        total_row = self.workspace.db.connection.execute(
            "SELECT COUNT(*) AS count FROM operations WHERE revision_id = ?",
            (revision_id,),
        ).fetchone()
        total_count = int(total_row["count"])
        rows = self.workspace.db.connection.execute(
            """SELECT id, sequence_number, operation_kind, target, payload_json
               FROM operations
               WHERE revision_id = ? AND sequence_number >= ?
               ORDER BY sequence_number
               LIMIT ?""",
            (revision_id, effective_start, effective_limit + 1),
        ).fetchall()

        page_rows = rows[:effective_limit]
        operations = [
            {
                "id": str(row["id"]),
                "sequence_number": int(row["sequence_number"]),
                "operation_kind": str(row["operation_kind"]),
                "target": row["target"],
                "payload": json.loads(str(row["payload_json"])),
            }
            for row in page_rows
        ]
        next_sequence_number = (
            int(rows[effective_limit]["sequence_number"])
            if len(rows) > effective_limit
            else None
        )
        truncated = next_sequence_number is not None
        return {
            "project": project,
            "revision": {
                "id": str(revision["id"]),
                "parent1_id": revision["parent1_id"],
                "parent2_id": revision["parent2_id"],
                "message": revision["message"],
                "author": revision["author"],
                "root_hash": revision["root_hash"],
                "created_at": revision["created_at"],
            },
            "start_sequence_number": effective_start,
            "limit": effective_limit,
            "total_operation_count": total_count,
            "returned_count": len(operations),
            "has_more": truncated,
            "truncated": truncated,
            "next_sequence_number": next_sequence_number,
            "limits": {"maximum_page_size": MAX_OPERATION_PAGE_SIZE},
            "operations": operations,
        }

    def summary(self, project: str, branch: str = "main") -> dict[str, Any]:
        project_id = self.workspace.project_id(project)
        branch_head = self.workspace.branch_head(project, branch)
        rows = self.workspace.db.connection.execute(
            """WITH RECURSIVE history(
                       id, parent1_id, parent2_id, message, author, created_at,
                       depth
                   ) AS (
                       SELECT id, parent1_id, parent2_id, message, author,
                              created_at, 0
                       FROM revisions
                       WHERE id = ? AND project_id = ?
                       UNION ALL
                       SELECT r.id, r.parent1_id, r.parent2_id, r.message,
                              r.author, r.created_at, h.depth + 1
                       FROM revisions r
                       JOIN history h ON r.id = h.parent1_id
                       WHERE r.project_id = ? AND h.depth < ?
                   )
                   SELECT id, parent1_id, parent2_id, message, author,
                          created_at, depth
                   FROM history
                   ORDER BY depth
                   LIMIT ?""",
            (
                branch_head,
                project_id,
                project_id,
                MAX_BRANCH_ACTIVITY_REVISIONS,
                MAX_BRANCH_ACTIVITY_REVISIONS + 1,
            ),
        ).fetchall()
        if not rows:
            raise NotFoundError(f"branch {branch!r} has no reachable revisions")
        if len(rows) > MAX_BRANCH_ACTIVITY_REVISIONS:
            raise ValidationError(
                "BRANCH_ACTIVITY_REVISION_LIMIT_EXCEEDED",
                "branch activity requires more than "
                f"{MAX_BRANCH_ACTIVITY_REVISIONS} first-parent revisions",
            )

        operation_rows = self.workspace.db.connection.execute(
            """WITH RECURSIVE history(id, parent1_id, depth) AS (
                       SELECT id, parent1_id, 0
                       FROM revisions
                       WHERE id = ? AND project_id = ?
                       UNION ALL
                       SELECT r.id, r.parent1_id, h.depth + 1
                       FROM revisions r
                       JOIN history h ON r.id = h.parent1_id
                       WHERE r.project_id = ? AND h.depth < ?
                   )
                   SELECT o.revision_id, o.operation_kind, COUNT(*) AS count
                   FROM history h
                   JOIN operations o ON o.revision_id = h.id
                   GROUP BY o.revision_id, o.operation_kind
                   ORDER BY o.revision_id, o.operation_kind""",
            (
                branch_head,
                project_id,
                project_id,
                MAX_BRANCH_ACTIVITY_REVISIONS,
            ),
        ).fetchall()

        counts_by_revision: dict[str, int] = defaultdict(int)
        operation_kind_counts: Counter[str] = Counter()
        for row in operation_rows:
            count = int(row["count"])
            counts_by_revision[str(row["revision_id"])] += count
            operation_kind_counts[str(row["operation_kind"])] += count

        operation_counts = [counts_by_revision[str(row["id"])] for row in rows]
        mutation_counts = [count for count in operation_counts if count > 0]
        authors = Counter(str(row["author"]) for row in rows)
        total_operations = sum(operation_counts)
        mutation_revision_count = len(mutation_counts)
        oldest = rows[-1]
        newest = rows[0]
        return {
            "project": project,
            "branch": branch,
            "head_revision_id": branch_head,
            "revision_count": len(rows),
            "first_parent_edge_count": max(0, len(rows) - 1),
            "merge_revision_count": sum(
                1 for row in rows if row["parent2_id"] is not None
            ),
            "operation_count": total_operations,
            "mutation_revision_count": mutation_revision_count,
            "zero_operation_revision_count": sum(
                1 for count in operation_counts if count == 0
            ),
            "single_operation_revision_count": sum(
                1 for count in operation_counts if count == 1
            ),
            "multi_operation_revision_count": sum(
                1 for count in operation_counts if count > 1
            ),
            "max_operations_per_revision": max(operation_counts, default=0),
            "average_operations_per_mutation_revision": (
                total_operations / mutation_revision_count
                if mutation_revision_count
                else 0.0
            ),
            "revision_count_avoided_by_grouping": sum(
                max(0, count - 1) for count in operation_counts
            ),
            "operation_kind_counts": dict(sorted(operation_kind_counts.items())),
            "author_revision_counts": dict(sorted(authors.items())),
            "newest_revision_id": str(newest["id"]),
            "newest_created_at": newest["created_at"],
            "oldest_revision_id": str(oldest["id"]),
            "oldest_created_at": oldest["created_at"],
            "complete": True,
            "truncated": False,
            "limits": {
                "maximum_first_parent_revisions": MAX_BRANCH_ACTIVITY_REVISIONS,
            },
        }

    def _is_first_parent_reachable(self, head: str, target: str) -> bool:
        current: str | None = head
        seen: set[str] = set()
        while current is not None:
            if current == target:
                return True
            if current in seen:
                raise ValidationError(
                    "REVISION_HISTORY_CYCLE",
                    "first-parent history contains a cycle",
                )
            if len(seen) >= MAX_BRANCH_ACTIVITY_REVISIONS:
                raise ValidationError(
                    "BRANCH_HISTORY_SCAN_LIMIT_EXCEEDED",
                    "first-parent reachability exceeds the revision scan limit "
                    f"{MAX_BRANCH_ACTIVITY_REVISIONS}",
                )
            seen.add(current)
            row = self.workspace.db.connection.execute(
                "SELECT parent1_id FROM revisions WHERE id = ?",
                (current,),
            ).fetchone()
            if row is None:
                return False
            current = row["parent1_id"]
        return False

    def _operations_for_revisions(
        self,
        revision_ids: list[str],
    ) -> dict[str, list[str]]:
        if not revision_ids:
            return {}
        placeholders = ",".join("?" for _ in revision_ids)
        rows = self.workspace.db.connection.execute(
            f"""SELECT revision_id, operation_kind
                FROM operations
                WHERE revision_id IN ({placeholders})
                ORDER BY revision_id, sequence_number""",
            revision_ids,
        ).fetchall()
        result: dict[str, list[str]] = defaultdict(list)
        for row in rows:
            result[str(row["revision_id"])].append(str(row["operation_kind"]))
        return dict(result)

    @staticmethod
    def _validate_history_limit(limit: int) -> None:
        require_bounded_int(
            limit,
            code="INVALID_HISTORY_LIMIT",
            name="limit",
            minimum=1,
            maximum=MAX_HISTORY_PAGE_SIZE,
        )

    @staticmethod
    def _validate_operation_limit(limit: int) -> None:
        require_bounded_int(
            limit,
            code="INVALID_OPERATION_LIMIT",
            name="limit",
            minimum=1,
            maximum=MAX_OPERATION_PAGE_SIZE,
        )
