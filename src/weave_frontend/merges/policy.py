"""Revisioned target-branch merge admission policies."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from ..errors import NotFoundError, ValidationError
from .validation_set import MAX_AFFECTED_TARGET_VALIDATIONS

MERGE_POLICY_FORMAT = "weave-merge-policy-v1"
MERGE_POLICY_TITLE = "Jacquard merge policy"
MERGE_POLICY_OPERATION = "set_merge_policy"


class MergePolicyRegistry:
    """Store immutable policies in revision context and resolve first-parent truth."""

    def __init__(self, workspace: Any) -> None:
        self.workspace = workspace

    def set(
        self,
        project: str,
        branch: str = "main",
        *,
        require_preflight: bool = True,
        require_affected_validation: bool = True,
        allow_uncovered_documents: bool = False,
        max_affected_targets: int = MAX_AFFECTED_TARGET_VALIDATIONS,
        author: str = "policy-agent",
    ) -> dict[str, Any]:
        policy = self._normalize(
            require_preflight=require_preflight,
            require_affected_validation=require_affected_validation,
            allow_uncovered_documents=allow_uncovered_documents,
            max_affected_targets=max_affected_targets,
        )
        body = self.workspace.db.canonical_json(policy)
        policy_hash = self.workspace.db.hash_value(policy)
        envelope_hash = self.workspace.db.hash_value(
            {
                "scope_kind": "project",
                "scope_name": project,
                "title": MERGE_POLICY_TITLE,
                "body": body,
            }
        )
        document_id = str(uuid4())
        with self.workspace.db.transaction() as connection:
            existing = connection.execute(
                "SELECT id FROM documents WHERE content_hash = ?",
                (envelope_hash,),
            ).fetchone()
            if existing is not None:
                document_id = str(existing["id"])
            else:
                connection.execute(
                    """INSERT INTO documents(
                           id, scope_kind, scope_name, title, body, content_hash
                       ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        document_id,
                        "project",
                        project,
                        MERGE_POLICY_TITLE,
                        body,
                        envelope_hash,
                    ),
                )

        state = self.workspace._state(project, branch)
        revision = self.workspace._commit(
            project,
            branch,
            state,
            message="set merge policy",
            author=author,
            operations=[
                (
                    MERGE_POLICY_OPERATION,
                    project,
                    {
                        "document_id": document_id,
                        "format": MERGE_POLICY_FORMAT,
                        "policy_hash": policy_hash,
                    },
                )
            ],
            extra_document_ids=[document_id],
        )
        return self._result(
            policy,
            configured=True,
            project=project,
            branch=branch,
            revision_id=revision,
            policy_revision_id=revision,
            document_id=document_id,
        )

    def get(
        self,
        project: str,
        branch: str = "main",
        *,
        revision_id: str | None = None,
    ) -> dict[str, Any]:
        revision = revision_id or self.workspace.branch_head(project, branch)
        self._require_project_revision(project, revision)
        current: str | None = revision
        while current is not None:
            row = self.workspace.db.connection.execute(
                """SELECT payload_json
                   FROM operations
                   WHERE revision_id = ? AND operation_kind = ?
                   ORDER BY sequence_number DESC
                   LIMIT 1""",
                (current, MERGE_POLICY_OPERATION),
            ).fetchone()
            if row is not None:
                payload = json.loads(str(row["payload_json"]))
                document_id = payload.get("document_id")
                if not isinstance(document_id, str) or not document_id:
                    raise ValidationError(
                        "INVALID_MERGE_POLICY",
                        "merge policy operation did not contain a document ID",
                    )
                policy = self._read_document(project, document_id)
                expected_hash = payload.get("policy_hash")
                actual_hash = self.workspace.db.hash_value(policy)
                if expected_hash != actual_hash:
                    raise ValidationError(
                        "INVALID_MERGE_POLICY",
                        "merge policy operation hash does not match its document",
                    )
                return self._result(
                    policy,
                    configured=True,
                    project=project,
                    branch=branch,
                    revision_id=revision,
                    policy_revision_id=current,
                    document_id=document_id,
                )
            parent = self.workspace.db.connection.execute(
                "SELECT parent1_id FROM revisions WHERE id = ?",
                (current,),
            ).fetchone()
            current = str(parent["parent1_id"]) if parent and parent["parent1_id"] else None

        policy = self._normalize(
            require_preflight=False,
            require_affected_validation=False,
            allow_uncovered_documents=True,
            max_affected_targets=MAX_AFFECTED_TARGET_VALIDATIONS,
        )
        return self._result(
            policy,
            configured=False,
            project=project,
            branch=branch,
            revision_id=revision,
            policy_revision_id=None,
            document_id=None,
        )

    def compare(
        self,
        project: str,
        target_branch: str,
        source_branch: str,
    ) -> dict[str, Any]:
        target = self.get(project, target_branch)
        source = self.get(project, source_branch)
        return {
            "target": target,
            "source": source,
            "source_policy_ignored": target["policy_hash"] != source["policy_hash"],
        }

    def _read_document(self, project: str, document_id: str) -> dict[str, Any]:
        row = self.workspace.db.connection.execute(
            """SELECT scope_kind, scope_name, title, body
               FROM documents WHERE id = ?""",
            (document_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"merge policy document {document_id!r} not found")
        if (
            row["scope_kind"] != "project"
            or row["scope_name"] != project
            or row["title"] != MERGE_POLICY_TITLE
        ):
            raise ValidationError(
                "INVALID_MERGE_POLICY",
                "merge policy document has the wrong project scope or title",
            )
        try:
            raw = json.loads(str(row["body"]))
        except json.JSONDecodeError as exc:
            raise ValidationError(
                "INVALID_MERGE_POLICY",
                "merge policy document is not valid JSON",
            ) from exc
        if not isinstance(raw, dict):
            raise ValidationError(
                "INVALID_MERGE_POLICY",
                "merge policy document must contain a JSON object",
            )
        return self._normalize(
            require_preflight=raw.get("require_preflight"),
            require_affected_validation=raw.get("require_affected_validation"),
            allow_uncovered_documents=raw.get("allow_uncovered_documents"),
            max_affected_targets=raw.get("max_affected_targets"),
            expected_format=raw.get("format"),
        )

    def _require_project_revision(self, project: str, revision_id: str) -> None:
        row = self.workspace.db.connection.execute(
            """SELECT 1
               FROM revisions r
               JOIN projects p ON p.id = r.project_id
               WHERE r.id = ? AND p.name = ?""",
            (revision_id, project),
        ).fetchone()
        if row is None:
            raise NotFoundError(
                f"revision {revision_id!r} does not belong to project {project!r}"
            )

    @staticmethod
    def _normalize(
        *,
        require_preflight: Any,
        require_affected_validation: Any,
        allow_uncovered_documents: Any,
        max_affected_targets: Any,
        expected_format: Any = MERGE_POLICY_FORMAT,
    ) -> dict[str, Any]:
        if expected_format != MERGE_POLICY_FORMAT:
            raise ValidationError(
                "INVALID_MERGE_POLICY",
                f"merge policy format must be {MERGE_POLICY_FORMAT!r}",
            )
        boolean_fields = {
            "require_preflight": require_preflight,
            "require_affected_validation": require_affected_validation,
            "allow_uncovered_documents": allow_uncovered_documents,
        }
        for name, value in boolean_fields.items():
            if not isinstance(value, bool):
                raise ValidationError(
                    "INVALID_MERGE_POLICY",
                    f"{name} must be a boolean",
                )
        if (
            isinstance(max_affected_targets, bool)
            or not isinstance(max_affected_targets, int)
            or max_affected_targets < 1
            or max_affected_targets > MAX_AFFECTED_TARGET_VALIDATIONS
        ):
            raise ValidationError(
                "INVALID_MERGE_POLICY",
                "max_affected_targets must be between 1 and "
                f"{MAX_AFFECTED_TARGET_VALIDATIONS}",
            )
        if require_preflight and not require_affected_validation:
            raise ValidationError(
                "INVALID_MERGE_POLICY",
                "require_preflight requires require_affected_validation",
            )
        return {
            "format": MERGE_POLICY_FORMAT,
            "require_preflight": require_preflight,
            "require_affected_validation": require_affected_validation,
            "allow_uncovered_documents": allow_uncovered_documents,
            "max_affected_targets": max_affected_targets,
        }

    def _result(
        self,
        policy: dict[str, Any],
        *,
        configured: bool,
        project: str,
        branch: str,
        revision_id: str,
        policy_revision_id: str | None,
        document_id: str | None,
    ) -> dict[str, Any]:
        return {
            **policy,
            "configured": configured,
            "project": project,
            "branch": branch,
            "revision_id": revision_id,
            "policy_revision_id": policy_revision_id,
            "document_id": document_id,
            "policy_hash": self.workspace.db.hash_value(policy),
        }
