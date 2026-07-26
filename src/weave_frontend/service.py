"""Grammar-neutral revision, branch, and merge mechanics.

The production S-expression workspace supplies structural validation and merge
hooks. This module deliberately knows nothing about Weave grammar, rendering, or
language semantics.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from .database import Database
from .errors import ConflictError, NotFoundError, ValidationError

JsonObject = dict[str, Any]


@dataclass(frozen=True)
class MergeResult:
    """Result of merging one immutable branch head into another."""

    revision_id: str
    target_branch: str
    source_branch: str
    changed_symbols: tuple[str, ...]


class RevisionWorkspace:
    """Versioned grammar-neutral workspace backed by one SQLite database."""

    def __init__(self, path: str | Path) -> None:
        self.db = Database(path)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> RevisionWorkspace:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def initialize(self, name: str, *, author: str = "system") -> tuple[str, str]:
        return self.db.initialize_project(name, author=author)

    def project_id(self, name: str) -> str:
        row = self.db.connection.execute(
            "SELECT id FROM projects WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"project {name!r} not found")
        return str(row["id"])

    def branch_head(self, project: str, branch: str = "main") -> str:
        project_id = self.project_id(project)
        row = self.db.connection.execute(
            "SELECT head_revision_id FROM branches WHERE project_id = ? AND name = ?",
            (project_id, branch),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"branch {branch!r} not found")
        return str(row["head_revision_id"])

    def create_branch(
        self,
        project: str,
        name: str,
        *,
        from_branch: str = "main",
    ) -> str:
        project_id = self.project_id(project)
        head = self.branch_head(project, from_branch)
        with self.db.transaction() as connection:
            connection.execute(
                "INSERT INTO branches(project_id, name, head_revision_id) VALUES (?, ?, ?)",
                (project_id, name, head),
            )
        return head

    def checkout(self, project: str, branch: str, revision_id: str) -> None:
        project_id = self.project_id(project)
        row = self.db.connection.execute(
            "SELECT 1 FROM revisions WHERE id = ? AND project_id = ?",
            (revision_id, project_id),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"revision {revision_id!r} not found")
        with self.db.transaction() as connection:
            connection.execute(
                "UPDATE branches SET head_revision_id = ? WHERE project_id = ? AND name = ?",
                (revision_id, project_id, branch),
            )

    def list_history(
        self,
        project: str,
        branch: str = "main",
        *,
        limit: int = 100,
    ) -> list[JsonObject]:
        current = self.branch_head(project, branch)
        history: list[JsonObject] = []
        while current and len(history) < limit:
            row = self.db.connection.execute(
                """SELECT id, parent1_id, parent2_id, message, author, root_hash,
                          created_at
                   FROM revisions WHERE id = ?""",
                (current,),
            ).fetchone()
            if row is None:
                break
            history.append(dict(row))
            current = row["parent1_id"]
        return history

    def merge(
        self,
        project: str,
        *,
        target_branch: str,
        source_branch: str,
        author: str = "merge-agent",
        expected_target_head: str | None = None,
        expected_source_head: str | None = None,
    ) -> MergeResult:
        """Merge current branch heads, rejecting stale expected heads atomically."""

        target_head = self.branch_head(project, target_branch)
        source_head = self.branch_head(project, source_branch)
        self._require_expected_head(
            target_branch,
            target_head,
            expected_target_head,
            code="STALE_MERGE_PREVIEW",
        )
        self._require_expected_head(
            source_branch,
            source_head,
            expected_source_head,
            code="STALE_MERGE_PREVIEW",
        )
        base = self._common_ancestor(target_head, source_head)
        base_state = self._state_at_revision(base)
        ours = self._state_at_revision(target_head)
        theirs = self._state_at_revision(source_head)
        merged, changed = self._merge_states(base_state, ours, theirs)
        self._validate_state(merged)
        revision = self._commit(
            project,
            target_branch,
            merged,
            message=f"merge {source_branch} into {target_branch}",
            author=author,
            operations=[
                (
                    "merge",
                    target_branch,
                    {
                        "source": source_branch,
                        "base": base,
                        "target_head": target_head,
                        "source_head": source_head,
                    },
                )
            ],
            parent2=source_head,
            expected_branch_heads={
                target_branch: target_head,
                source_branch: source_head,
            },
            stale_error_code="STALE_MERGE_PREVIEW",
        )
        return MergeResult(
            revision,
            target_branch,
            source_branch,
            tuple(sorted(changed)),
        )

    @staticmethod
    def _require_expected_head(
        branch: str,
        actual: str,
        expected: str | None,
        *,
        code: str,
    ) -> None:
        if expected is not None and actual != expected:
            raise ValidationError(
                code,
                f"branch {branch!r} advanced from {expected!r} to {actual!r}",
            )

    @staticmethod
    def _validate_expected_revision_id(expected_revision_id: str | None) -> None:
        if expected_revision_id is not None and (
            not isinstance(expected_revision_id, str) or not expected_revision_id
        ):
            raise ValidationError(
                "INVALID_EXPECTED_REVISION_ID",
                "expected_revision_id must be a non-empty string or null",
            )

    def _state(self, project: str, branch: str) -> dict[str, JsonObject]:
        return self._state_at_revision(self.branch_head(project, branch))

    def _state_for_write(
        self,
        project: str,
        branch: str,
        *,
        expected_revision_id: str | None = None,
    ) -> tuple[str, dict[str, JsonObject]]:
        """Capture one branch head for a compare-and-set publication attempt."""

        self._validate_expected_revision_id(expected_revision_id)
        base_revision_id = self.branch_head(project, branch)
        self._require_expected_head(
            branch,
            base_revision_id,
            expected_revision_id,
            code="STALE_BRANCH_HEAD",
        )
        return base_revision_id, self._state_at_revision(base_revision_id)

    def _state_at_revision(self, revision_id: str) -> dict[str, JsonObject]:
        rows = self.db.connection.execute(
            "SELECT qualified_name, ast_json FROM module_snapshots WHERE revision_id = ?",
            (revision_id,),
        ).fetchall()
        return {
            str(row["qualified_name"]): json.loads(row["ast_json"])
            for row in rows
        }

    def _commit(
        self,
        project: str,
        branch: str,
        modules: dict[str, JsonObject],
        *,
        message: str,
        author: str,
        operations: Iterable[tuple[str, str | None, JsonObject]],
        parent2: str | None = None,
        extra_document_ids: Iterable[str] = (),
        expected_branch_heads: dict[str, str] | None = None,
        stale_error_code: str = "STALE_BRANCH_HEAD",
    ) -> str:
        project_id = self.project_id(project)
        parent1 = (
            expected_branch_heads[branch]
            if expected_branch_heads is not None and branch in expected_branch_heads
            else self.branch_head(project, branch)
        )
        revision_id = str(uuid4())
        root_hash = self.db.hash_value(modules)
        parent_documents = self.db.connection.execute(
            "SELECT document_id FROM revision_documents WHERE revision_id = ?",
            (parent1,),
        ).fetchall()
        document_ids = {str(row["document_id"]) for row in parent_documents}
        document_ids.update(extra_document_ids)
        with self.db.transaction() as connection:
            if expected_branch_heads is not None:
                for expected_branch, expected_head in sorted(
                    expected_branch_heads.items()
                ):
                    row = connection.execute(
                        """SELECT head_revision_id FROM branches
                           WHERE project_id = ? AND name = ?""",
                        (project_id, expected_branch),
                    ).fetchone()
                    actual_head = str(row["head_revision_id"]) if row is not None else None
                    if actual_head != expected_head:
                        raise ValidationError(
                            stale_error_code,
                            f"branch {expected_branch!r} advanced from "
                            f"{expected_head!r} to {actual_head!r}",
                        )

            connection.execute(
                """INSERT INTO revisions(
                       id, project_id, parent1_id, parent2_id, message, author, root_hash
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    revision_id,
                    project_id,
                    parent1,
                    parent2,
                    message,
                    author,
                    root_hash,
                ),
            )
            for module_name, ast in sorted(modules.items()):
                canonical = self.db.canonical_json(ast)
                connection.execute(
                    """INSERT INTO module_snapshots(
                           revision_id, qualified_name, ast_json, ast_hash
                       ) VALUES (?, ?, ?, ?)""",
                    (
                        revision_id,
                        module_name,
                        canonical,
                        self.db.hash_value(ast),
                    ),
                )
            for sequence, (kind, target, payload) in enumerate(operations):
                connection.execute(
                    """INSERT INTO operations(
                           id, revision_id, sequence_number, operation_kind,
                           target, payload_json
                       ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid4()),
                        revision_id,
                        sequence,
                        kind,
                        target,
                        self.db.canonical_json(payload),
                    ),
                )
            for document_id in sorted(document_ids):
                connection.execute(
                    """INSERT INTO revision_documents(revision_id, document_id)
                       VALUES (?, ?)""",
                    (revision_id, document_id),
                )
            if expected_branch_heads is None:
                connection.execute(
                    """UPDATE branches SET head_revision_id = ?
                       WHERE project_id = ? AND name = ?""",
                    (revision_id, project_id, branch),
                )
            else:
                updated = connection.execute(
                    """UPDATE branches SET head_revision_id = ?
                       WHERE project_id = ? AND name = ? AND head_revision_id = ?""",
                    (revision_id, project_id, branch, parent1),
                )
                if updated.rowcount != 1:
                    raise ValidationError(
                        stale_error_code,
                        f"branch {branch!r} advanced while publishing the revision",
                    )
        return revision_id

    def _parents(self, revision: str) -> tuple[str | None, str | None]:
        row = self.db.connection.execute(
            "SELECT parent1_id, parent2_id FROM revisions WHERE id = ?",
            (revision,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"revision {revision!r} not found")
        return row["parent1_id"], row["parent2_id"]

    def _ancestor_distances(self, revision: str) -> dict[str, int]:
        distances = {revision: 0}
        queue: deque[str] = deque([revision])
        while queue:
            current = queue.popleft()
            for parent in self._parents(current):
                if parent is not None and parent not in distances:
                    distances[parent] = distances[current] + 1
                    queue.append(parent)
        return distances

    def _common_ancestor(self, left: str, right: str) -> str:
        left_distances = self._ancestor_distances(left)
        right_distances = self._ancestor_distances(right)
        common = set(left_distances) & set(right_distances)
        if not common:
            raise ConflictError(["branches have no common ancestor"])
        return min(
            common,
            key=lambda item: left_distances[item] + right_distances[item],
        )

    @classmethod
    def _validate_state(cls, state: dict[str, JsonObject]) -> None:
        raise NotImplementedError

    @classmethod
    def _merge_states(
        cls,
        base: dict[str, JsonObject],
        ours: dict[str, JsonObject],
        theirs: dict[str, JsonObject],
    ) -> tuple[dict[str, JsonObject], set[str]]:
        raise NotImplementedError


# Internal compatibility for the existing S-expression service import. The public
# package no longer exports this name.
Workspace = RevisionWorkspace
