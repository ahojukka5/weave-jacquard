"""Race-safe public workspace for branch, program, node, and context writes."""

from __future__ import annotations

import sqlite3
from typing import Any
from uuid import uuid4

from .concurrent_sexpr import SExpressionWorkspace as _NodeConcurrentWorkspace
from .errors import NotFoundError, ValidationError
from .sexpr import make_atom, make_form, parse_source, validate_tree


class SExpressionWorkspace(_NodeConcurrentWorkspace):
    """Public workspace whose direct writes compare-and-set branch heads."""

    def create_branch(
        self,
        project: str,
        name: str,
        *,
        from_branch: str = "main",
        expected_revision_id: str | None = None,
    ) -> str:
        self._validate_expected_revision_id(expected_revision_id)
        project_id = self.project_id(project)
        base_revision_id = self.branch_head(project, from_branch)
        self._require_expected_head(
            from_branch,
            base_revision_id,
            expected_revision_id,
            code="STALE_BRANCH_HEAD",
        )
        try:
            with self.db.transaction() as connection:
                row = connection.execute(
                    """SELECT head_revision_id FROM branches
                       WHERE project_id = ? AND name = ?""",
                    (project_id, from_branch),
                ).fetchone()
                actual_head = str(row["head_revision_id"]) if row is not None else None
                if actual_head != base_revision_id:
                    raise ValidationError(
                        "STALE_BRANCH_HEAD",
                        f"branch {from_branch!r} advanced from "
                        f"{base_revision_id!r} to {actual_head!r}",
                    )
                connection.execute(
                    """INSERT INTO branches(project_id, name, head_revision_id)
                       VALUES (?, ?, ?)""",
                    (project_id, name, base_revision_id),
                )
        except sqlite3.IntegrityError as exc:
            raise ValidationError(
                "DUPLICATE_BRANCH",
                f"branch {name!r} already exists",
            ) from exc
        return base_revision_id

    def create_branch_at_revision(
        self,
        project: str,
        name: str,
        revision_id: str,
    ) -> str:
        if not isinstance(revision_id, str) or not revision_id:
            raise ValidationError(
                "INVALID_REVISION_ID",
                "revision_id must be a non-empty string",
            )
        project_id = self.project_id(project)
        row = self.db.connection.execute(
            "SELECT 1 FROM revisions WHERE id = ? AND project_id = ?",
            (revision_id, project_id),
        ).fetchone()
        if row is None:
            raise NotFoundError(
                f"revision {revision_id!r} does not belong to project {project!r}"
            )
        try:
            with self.db.transaction() as connection:
                connection.execute(
                    """INSERT INTO branches(project_id, name, head_revision_id)
                       VALUES (?, ?, ?)""",
                    (project_id, name, revision_id),
                )
        except sqlite3.IntegrityError as exc:
            raise ValidationError(
                "DUPLICATE_BRANCH",
                f"branch {name!r} already exists",
            ) from exc
        return revision_id

    def create_program(
        self,
        project: str,
        branch: str,
        document: str,
        *,
        program_name: str,
        version: str = "0.1",
        expected_revision_id: str | None = None,
        author: str = "agent",
    ) -> dict[str, Any]:
        base_revision_id, state = self._state_for_write(
            project,
            branch,
            expected_revision_id=expected_revision_id,
        )
        if document in state:
            raise ValidationError(
                "DUPLICATE_DOCUMENT",
                f"document {document!r} already exists",
            )
        root = make_form("program")
        name_form = make_form("name")
        name_form["children"].append(make_atom("string", program_name))
        version_form = make_form("version")
        version_form["children"].append(make_atom("string", version))
        root["children"].extend([name_form, version_form])
        validate_tree(root)
        state[document] = root
        revision = self._commit_program_mutation(
            project,
            branch,
            base_revision_id,
            state,
            message=f"create program {document}",
            author=author,
            operation=("create_program", root["id"], {"document": document}),
        )
        result = self._mutation_result(
            revision,
            branch,
            document,
            root,
            [root["id"]],
        )
        result["base_revision_id"] = base_revision_id
        return result

    def import_program(
        self,
        project: str,
        branch: str,
        document: str,
        source: str,
        *,
        replace: bool = False,
        expected_revision_id: str | None = None,
        author: str = "agent",
    ) -> dict[str, Any]:
        root = parse_source(source)
        base_revision_id, state = self._state_for_write(
            project,
            branch,
            expected_revision_id=expected_revision_id,
        )
        if document in state and not replace:
            raise ValidationError(
                "DUPLICATE_DOCUMENT",
                f"document {document!r} already exists",
            )
        state[document] = root
        revision = self._commit_program_mutation(
            project,
            branch,
            base_revision_id,
            state,
            message=f"{'replace' if replace else 'import'} program {document}",
            author=author,
            operation=("import_program", root["id"], {"document": document}),
        )
        result = self._mutation_result(
            revision,
            branch,
            document,
            root,
            [root["id"]],
        )
        result["base_revision_id"] = base_revision_id
        return result

    def add_context(
        self,
        project: str,
        branch: str,
        *,
        scope_kind: str,
        scope_name: str,
        title: str,
        body: str,
        expected_revision_id: str | None = None,
        author: str = "agent",
    ) -> dict[str, Any]:
        if scope_kind not in {"project", "document", "symbol"}:
            raise ValidationError(
                "INVALID_SCOPE",
                "scope_kind must be project, document, or symbol",
            )
        base_revision_id, state = self._state_for_write(
            project,
            branch,
            expected_revision_id=expected_revision_id,
        )
        revision, document_id = self._commit_content_document(
            project,
            branch,
            base_revision_id,
            state,
            scope_kind=scope_kind,
            scope_name=scope_name,
            title=title,
            body=body,
            message=f"add context {title}",
            author=author,
            operation_kind="add_context",
            operation_target=scope_name,
            operation_payload={},
        )
        return {
            "revision_id": revision,
            "base_revision_id": base_revision_id,
            "branch": branch,
            "document_id": document_id,
        }

    def _commit_program_mutation(
        self,
        project: str,
        branch: str,
        base_revision_id: str,
        state: dict[str, dict[str, Any]],
        *,
        message: str,
        author: str,
        operation: tuple[str, str | None, dict[str, Any]],
    ) -> str:
        return self._commit(
            project,
            branch,
            state,
            message=message,
            author=author,
            operations=[operation],
            expected_branch_heads={branch: base_revision_id},
            stale_error_code="STALE_BRANCH_HEAD",
        )

    def _commit_content_document(
        self,
        project: str,
        branch: str,
        base_revision_id: str,
        state: dict[str, dict[str, Any]],
        *,
        scope_kind: str,
        scope_name: str,
        title: str,
        body: str,
        message: str,
        author: str,
        operation_kind: str,
        operation_target: str | None,
        operation_payload: dict[str, Any],
    ) -> tuple[str, str]:
        content_hash = self.db.hash_value(
            {
                "scope_kind": scope_kind,
                "scope_name": scope_name,
                "title": title,
                "body": body,
            }
        )
        prepared: dict[str, str] = {}

        def prepare_transaction(connection):
            existing = connection.execute(
                "SELECT id FROM documents WHERE content_hash = ?",
                (content_hash,),
            ).fetchone()
            if existing is not None:
                document_id = str(existing["id"])
            else:
                document_id = str(uuid4())
                connection.execute(
                    """INSERT INTO documents(
                           id, scope_kind, scope_name, title, body, content_hash
                       ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        document_id,
                        scope_kind,
                        scope_name,
                        title,
                        body,
                        content_hash,
                    ),
                )
            prepared["document_id"] = document_id
            payload = dict(operation_payload)
            payload["document_id"] = document_id
            return (
                [(operation_kind, operation_target, payload)],
                [document_id],
            )

        revision = self._commit(
            project,
            branch,
            state,
            message=message,
            author=author,
            operations=(),
            expected_branch_heads={branch: base_revision_id},
            stale_error_code="STALE_BRANCH_HEAD",
            prepare_transaction=prepare_transaction,
        )
        return revision, prepared["document_id"]
