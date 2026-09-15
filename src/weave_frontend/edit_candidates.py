"""Unpublished working candidates for structural edits and qualification."""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import uuid4

from .batch_edit import EditBatchExecutor
from .errors import NotFoundError, ValidationError
from .sexpr import JsonObject, render_node, validate_tree

CANDIDATE_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
CANDIDATE_STATUSES = frozenset({"open", "abandoned", "published"})
QUALIFICATION_LEVELS = ("syntactic", "compiler")


class EditCandidateService:
    """Accumulate immutable edits off a published branch until publication."""

    def __init__(self, workspace: Any) -> None:
        self.workspace = workspace
        self.batches = EditBatchExecutor(workspace)

    def open(
        self,
        project: str,
        name: str,
        *,
        branch: str = "main",
        base_revision_id: str | None = None,
    ) -> dict[str, Any]:
        if not CANDIDATE_NAME_PATTERN.match(name):
            raise ValidationError(
                "INVALID_CANDIDATE_NAME",
                "candidate name must match [A-Za-z][A-Za-z0-9_-]{0,63}",
            )
        project_id = self.workspace.project_id(project)
        branch_head = self.workspace.branch_head(project, branch)
        base = base_revision_id or branch_head
        if base_revision_id is not None:
            self._require_project_revision(project, base)
        candidate_id = str(uuid4())
        with self.workspace.db.transaction() as connection:
            existing = connection.execute(
                """SELECT id FROM edit_candidates
                   WHERE project_id = ? AND name = ? AND status = 'open'""",
                (project_id, name),
            ).fetchone()
            if existing is not None:
                raise ValidationError(
                    "DUPLICATE_CANDIDATE_NAME",
                    f"open candidate {name!r} already exists",
                )
            connection.execute(
                """INSERT INTO edit_candidates(
                       id, project_id, name, base_revision_id, head_revision_id,
                       status
                   ) VALUES (?, ?, ?, ?, ?, 'open')""",
                (candidate_id, project_id, name, base, base),
            )
        return self.inspect(project, candidate_id)

    def inspect(self, project: str, candidate_id: str) -> dict[str, Any]:
        candidate = self._load(project, candidate_id)
        qualification = self._latest_qualification(candidate["id"])
        return {
            **candidate,
            "edits": self._edit_history(
                candidate["head_revision_id"],
                candidate["base_revision_id"],
            ),
            "qualification": self._qualification_view(
                candidate["head_revision_id"],
                qualification,
            ),
            "publication": {
                "status": candidate["status"],
                "published_branch": candidate["published_branch"],
                "published_revision_id": candidate["published_revision_id"],
            },
        }

    def apply_batch(
        self,
        project: str,
        candidate_id: str,
        document: str,
        operations: list[dict[str, Any]],
        *,
        expected_revision_id: str | None = None,
        message: str | None = None,
        author: str = "agent",
        include_operation_results: bool = False,
    ) -> dict[str, Any]:
        candidate = self._require_open(project, candidate_id)
        base_revision_id = str(candidate["head_revision_id"])
        if (
            expected_revision_id is not None
            and expected_revision_id != base_revision_id
        ):
            raise ValidationError(
                "STALE_REVISION",
                "candidate head does not match expected_revision_id",
            )
        state = self.workspace._state_at_revision(base_revision_id)
        try:
            root = state[document]
        except KeyError as exc:
            raise NotFoundError(
                f"document {document!r} not found in candidate {candidate_id!r}"
            ) from exc
        transformed = self.batches.transform(root, operations)
        self.workspace._validate_state(state)
        revision_id = self._commit_candidate_revision(
            project,
            candidate,
            state,
            base_revision_id=base_revision_id,
            message=message or f"apply {len(operations)} candidate edits",
            author=author,
            operations=transformed["operation_log"],
        )
        response: dict[str, Any] = {
            "candidate_id": candidate["id"],
            "revision_id": revision_id,
            "base_revision_id": candidate["base_revision_id"],
            "previous_revision_id": base_revision_id,
            "document": document,
            "root_node_id": root["id"],
            "operation_count": transformed["operation_count"],
            "created_node_count": transformed["created_node_count"],
            "deleted_node_count": transformed["deleted_node_count"],
            "aliases": transformed["aliases"],
            "published": False,
        }
        if include_operation_results:
            response["operation_results"] = transformed["operation_results"]
        return response

    def qualify(
        self,
        project: str,
        candidate_id: str,
        *,
        level: str = "syntactic",
        expected_revision_id: str | None = None,
    ) -> dict[str, Any]:
        if level not in QUALIFICATION_LEVELS:
            raise ValidationError(
                "INVALID_QUALIFICATION_LEVEL",
                f"level must be one of {list(QUALIFICATION_LEVELS)}",
            )
        candidate = self._require_open(project, candidate_id)
        head = str(candidate["head_revision_id"])
        if expected_revision_id is not None and expected_revision_id != head:
            raise ValidationError(
                "STALE_REVISION",
                "qualification expected_revision_id does not match candidate head",
            )
        state = self.workspace._state_at_revision(head)
        syntactic = self._syntactic_evidence(state)
        compiler = None
        status = "passed" if syntactic["valid"] else "failed"
        if level == "compiler":
            compiler = self._compiler_evidence(state)
            if compiler.get("available") is False:
                status = "unavailable"
            elif compiler.get("valid") is not True or status != "passed":
                status = "failed"
        evidence = {
            "level": level,
            "syntactic": syntactic,
            "compiler": compiler,
        }
        qualification_id = str(uuid4())
        compiler_identity = self._compiler_identity()
        with self.workspace.db.transaction() as connection:
            current = connection.execute(
                "SELECT head_revision_id, status FROM edit_candidates WHERE id = ?",
                (candidate["id"],),
            ).fetchone()
            if current is None or str(current["status"]) != "open":
                raise ValidationError(
                    "CANDIDATE_CONFLICT",
                    "candidate is no longer open",
                )
            if str(current["head_revision_id"]) != head:
                raise ValidationError(
                    "STALE_REVISION",
                    "candidate advanced while qualification was recorded",
                )
            connection.execute(
                """INSERT INTO candidate_qualifications(
                       id, candidate_id, revision_id, level, status,
                       compiler_identity_json, evidence_json
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    qualification_id,
                    candidate["id"],
                    head,
                    level,
                    status,
                    self.workspace.db.canonical_json(compiler_identity),
                    self.workspace.db.canonical_json(evidence),
                ),
            )
        return {
            "qualification_id": qualification_id,
            "candidate_id": candidate["id"],
            "revision_id": head,
            "level": level,
            "status": status,
            "compiler_identity": compiler_identity,
            "evidence": evidence,
        }

    def publish(
        self,
        project: str,
        candidate_id: str,
        branch: str,
        *,
        require_level: str | None = None,
        expected_base_revision_id: str | None = None,
        expected_revision_id: str | None = None,
    ) -> dict[str, Any]:
        candidate = self._require_open(project, candidate_id)
        head = str(candidate["head_revision_id"])
        base = str(candidate["base_revision_id"])
        if expected_revision_id is not None and expected_revision_id != head:
            raise ValidationError(
                "STALE_REVISION",
                "publication expected_revision_id does not match candidate head",
            )
        required_base = expected_base_revision_id or base
        if require_level is not None:
            qualification = self._latest_qualification(candidate["id"])
            view = self._qualification_view(head, qualification)
            if view["status"] != "passed" or view["level"] != require_level:
                raise ValidationError(
                    "QUALIFICATION_FAILURE",
                    "candidate lacks a current passing qualification at the required level",
                    qualification=view,
                )
            if view["stale"]:
                raise ValidationError(
                    "STALE_QUALIFICATION",
                    "qualification no longer refers to the candidate head",
                    qualification=view,
                )
        project_id = self.workspace.project_id(project)
        with self.workspace.db.transaction() as connection:
            branch_row = connection.execute(
                """SELECT head_revision_id FROM branches
                   WHERE project_id = ? AND name = ?""",
                (project_id, branch),
            ).fetchone()
            if branch_row is None:
                raise NotFoundError(f"branch {branch!r} not found")
            actual_head = str(branch_row["head_revision_id"])
            if actual_head != required_base:
                raise ValidationError(
                    "PUBLICATION_RACE",
                    (
                        f"branch {branch!r} is at {actual_head!r}, "
                        f"not candidate base {required_base!r}"
                    ),
                )
            candidate_row = connection.execute(
                """SELECT head_revision_id, status FROM edit_candidates WHERE id = ?""",
                (candidate["id"],),
            ).fetchone()
            if (
                candidate_row is None
                or str(candidate_row["status"]) != "open"
                or str(candidate_row["head_revision_id"]) != head
            ):
                raise ValidationError(
                    "CANDIDATE_CONFLICT",
                    "candidate changed during publication",
                )
            updated = connection.execute(
                """UPDATE branches SET head_revision_id = ?
                   WHERE project_id = ? AND name = ? AND head_revision_id = ?""",
                (head, project_id, branch, required_base),
            )
            if updated.rowcount != 1:
                raise ValidationError(
                    "PUBLICATION_RACE",
                    f"branch {branch!r} advanced while publishing the candidate",
                )
            connection.execute(
                """UPDATE edit_candidates
                   SET status = 'published',
                       published_branch = ?,
                       published_revision_id = ?
                   WHERE id = ?""",
                (branch, head, candidate["id"]),
            )
        return {
            "candidate_id": candidate["id"],
            "revision_id": head,
            "base_revision_id": base,
            "branch": branch,
            "published": True,
        }

    def abandon(self, project: str, candidate_id: str) -> dict[str, Any]:
        candidate = self._require_open(project, candidate_id)
        with self.workspace.db.transaction() as connection:
            updated = connection.execute(
                """UPDATE edit_candidates SET status = 'abandoned'
                   WHERE id = ? AND status = 'open'""",
                (candidate["id"],),
            )
            if updated.rowcount != 1:
                raise ValidationError(
                    "CANDIDATE_CONFLICT",
                    "candidate is no longer open",
                )
        candidate["status"] = "abandoned"
        return {"candidate_id": candidate["id"], "status": "abandoned"}

    def revert_last(self, project: str, candidate_id: str) -> dict[str, Any]:
        candidate = self._require_open(project, candidate_id)
        head = str(candidate["head_revision_id"])
        base = str(candidate["base_revision_id"])
        if head == base:
            raise ValidationError(
                "INVALID_EDIT",
                "candidate has no edits to revert",
            )
        parent1, _parent2 = self.workspace._parents(head)
        if parent1 is None:
            raise ValidationError(
                "INVALID_EDIT",
                "candidate head has no parent revision",
            )
        with self.workspace.db.transaction() as connection:
            updated = connection.execute(
                """UPDATE edit_candidates
                   SET head_revision_id = ?
                   WHERE id = ? AND status = 'open' AND head_revision_id = ?""",
                (parent1, candidate["id"], head),
            )
            if updated.rowcount != 1:
                raise ValidationError(
                    "STALE_REVISION",
                    "candidate advanced while reverting",
                )
        return {
            "candidate_id": candidate["id"],
            "revision_id": parent1,
            "reverted_revision_id": head,
        }

    def replay(
        self,
        project: str,
        name: str,
        operations: list[dict[str, Any]],
        *,
        branch: str = "main",
        base_revision_id: str | None = None,
        document: str,
    ) -> dict[str, Any]:
        opened = self.open(
            project,
            name,
            branch=branch,
            base_revision_id=base_revision_id,
        )
        applied = self.apply_batch(
            project,
            opened["id"],
            document,
            operations,
            expected_revision_id=opened["head_revision_id"],
        )
        return {
            **applied,
            "candidate_id": opened["id"],
            "replayed": True,
        }

    def _commit_candidate_revision(
        self,
        project: str,
        candidate: dict[str, Any],
        modules: dict[str, JsonObject],
        *,
        base_revision_id: str,
        message: str,
        author: str,
        operations: list[tuple[str, str | None, JsonObject]],
    ) -> str:
        project_id = self.workspace.project_id(project)
        revision_id = str(uuid4())
        root_hash = self.workspace.db.hash_value(modules)
        with self.workspace.db.transaction() as connection:
            current = connection.execute(
                """SELECT head_revision_id, status FROM edit_candidates WHERE id = ?""",
                (candidate["id"],),
            ).fetchone()
            if (
                current is None
                or str(current["status"]) != "open"
                or str(current["head_revision_id"]) != base_revision_id
            ):
                raise ValidationError(
                    "STALE_REVISION",
                    "candidate head advanced while the edit was committed",
                )
            self.workspace._insert_revision(
                connection,
                revision_id=revision_id,
                project_id=project_id,
                parent1=base_revision_id,
                parent2=None,
                message=message,
                author=author,
                root_hash=root_hash,
                modules=modules,
                operations=operations,
                extra_document_ids=(),
            )
            connection.execute(
                """UPDATE edit_candidates SET head_revision_id = ?
                   WHERE id = ? AND head_revision_id = ?""",
                (revision_id, candidate["id"], base_revision_id),
            )
        return revision_id

    def _load(self, project: str, candidate_id: str) -> dict[str, Any]:
        row = self.workspace.db.connection.execute(
            """SELECT c.id, p.name AS project, c.name, c.base_revision_id,
                      c.head_revision_id, c.status, c.published_branch,
                      c.published_revision_id
               FROM edit_candidates c
               JOIN projects p ON p.id = c.project_id
               WHERE c.id = ? AND p.name = ?""",
            (candidate_id, project),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"candidate {candidate_id!r} not found")
        return dict(row)

    def _require_open(self, project: str, candidate_id: str) -> dict[str, Any]:
        candidate = self._load(project, candidate_id)
        if candidate["status"] != "open":
            raise ValidationError(
                "CANDIDATE_CONFLICT",
                f"candidate is {candidate['status']}",
            )
        return candidate

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

    def _edit_history(self, head: str, base: str) -> list[dict[str, Any]]:
        history: list[dict[str, Any]] = []
        current = head
        seen: set[str] = set()
        while current != base:
            if current in seen:
                raise ValidationError(
                    "INVALID_EDIT",
                    "candidate history contains a cycle",
                )
            seen.add(current)
            parent1, _parent2 = self.workspace._parents(current)
            rows = self.workspace.db.connection.execute(
                """SELECT sequence_number, operation_kind, target, payload_json
                   FROM operations
                   WHERE revision_id = ?
                   ORDER BY sequence_number""",
                (current,),
            ).fetchall()
            history.append(
                {
                    "revision_id": current,
                    "parent_revision_id": parent1,
                    "operations": [
                        {
                            "sequence": int(row["sequence_number"]),
                            "op": row["operation_kind"],
                            "target": row["target"],
                            "payload": json.loads(row["payload_json"]),
                        }
                        for row in rows
                    ],
                }
            )
            if parent1 is None:
                break
            current = parent1
        history.reverse()
        return history

    def _latest_qualification(self, candidate_id: str) -> dict[str, Any] | None:
        row = self.workspace.db.connection.execute(
            """SELECT id, revision_id, level, status, compiler_identity_json,
                      evidence_json
               FROM candidate_qualifications
               WHERE candidate_id = ?
               ORDER BY created_at DESC, id DESC
               LIMIT 1""",
            (candidate_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "qualification_id": row["id"],
            "revision_id": row["revision_id"],
            "level": row["level"],
            "status": row["status"],
            "compiler_identity": json.loads(row["compiler_identity_json"]),
            "evidence": json.loads(row["evidence_json"]),
        }

    @staticmethod
    def _qualification_view(
        head_revision_id: str,
        qualification: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if qualification is None:
            return {
                "status": "none",
                "stale": False,
                "invalidated_by": [],
            }
        stale_reasons: list[str] = []
        if qualification["revision_id"] != head_revision_id:
            stale_reasons.append("candidate_content_changed")
        return {
            **qualification,
            "stale": bool(stale_reasons),
            "invalidated_by": stale_reasons,
        }

    def _syntactic_evidence(self, state: dict[str, JsonObject]) -> dict[str, Any]:
        documents = []
        valid = True
        for name, root in sorted(state.items()):
            try:
                validate_tree(root)
                documents.append({"document": name, "valid": True})
            except ValidationError as exc:
                valid = False
                documents.append(
                    {
                        "document": name,
                        "valid": False,
                        "error": exc.as_dict(),
                    }
                )
        return {"valid": valid, "documents": documents}

    def _compiler_evidence(self, state: dict[str, JsonObject]) -> dict[str, Any]:
        sources = [
            (name, render_node(root))
            for name, root in sorted(state.items())
        ]
        if not sources:
            return {"available": True, "valid": True, "documents": []}
        result = self.workspace.validator.validate_sources(sources)
        return result

    def _compiler_identity(self) -> dict[str, Any]:
        validator = getattr(self.workspace, "validator", None)
        binary = getattr(validator, "binary", None)
        if binary is None:
            return {"available": False}
        return {
            "available": True,
            "binary_name": str(binary),
        }
