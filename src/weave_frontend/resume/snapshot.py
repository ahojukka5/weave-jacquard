"""Bounded revision-consistent orientation snapshots for restarted agents."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol

from ..builds import BUILD_TARGET_PREFIX, BuildTargetRegistry
from ..errors import NotFoundError, ValidationError
from ..merges import MergePolicyRegistry
from ..sexpr import head_symbol, walk_nodes
from ..source_map import render_with_node_map

RESUME_SNAPSHOT_FORMAT = "weave-agent-resume-snapshot-v1"
MAX_RESUME_DOCUMENTS = 200
MAX_RESUME_TARGETS = 100
MAX_RESUME_TARGET_SOURCES = 200
MAX_RESUME_CONTEXTS = 100
MAX_RESUME_BRANCHES = 200
MAX_RESUME_HISTORY = 50
MAX_RESUME_OPERATIONS = 200
MAX_CONTEXT_PREVIEW_CHARS = 512


class _Workspace(Protocol):
    db: Any

    def project_id(self, name: str) -> str: ...

    def branch_head(self, project: str, branch: str = "main") -> str: ...

    def _state_at_revision(self, revision_id: str) -> dict[str, dict[str, Any]]: ...


class ResumeSnapshotService:
    """Compose one deterministic bounded read from an exact immutable revision."""

    def __init__(
        self,
        workspace: _Workspace,
        targets: BuildTargetRegistry,
        policies: MergePolicyRegistry,
    ) -> None:
        self.workspace = workspace
        self.targets = targets
        self.policies = policies

    def snapshot(
        self,
        project: str,
        branch: str = "main",
        *,
        revision_id: str | None = None,
        document_limit: int = 100,
        target_limit: int = 50,
        target_source_limit: int = 50,
        context_limit: int = 20,
        branch_limit: int = 50,
        history_limit: int = 10,
        operation_limit: int = 50,
    ) -> dict[str, Any]:
        """Return bounded orientation evidence without mixing revision state."""

        self._validate_limit("document_limit", document_limit, MAX_RESUME_DOCUMENTS)
        self._validate_limit("target_limit", target_limit, MAX_RESUME_TARGETS)
        self._validate_limit(
            "target_source_limit",
            target_source_limit,
            MAX_RESUME_TARGET_SOURCES,
        )
        self._validate_limit("context_limit", context_limit, MAX_RESUME_CONTEXTS)
        self._validate_limit("branch_limit", branch_limit, MAX_RESUME_BRANCHES)
        self._validate_limit("history_limit", history_limit, MAX_RESUME_HISTORY)
        self._validate_limit("operation_limit", operation_limit, MAX_RESUME_OPERATIONS)

        branch_head_revision_id = self.workspace.branch_head(project, branch)
        selected_revision_id = revision_id or branch_head_revision_id
        revision = self._revision(project, selected_revision_id)
        modules = self._revision_modules(selected_revision_id)
        program_entries, total_program_count = self._programs(
            modules,
            selected_revision_id,
            limit=document_limit,
        )
        target_entries, total_target_count = self._targets(
            modules,
            selected_revision_id,
            limit=target_limit,
            source_limit=target_source_limit,
        )
        branch_entries, total_branch_count = self._branches(
            project,
            limit=branch_limit,
        )
        contexts, total_context_count = self._contexts(
            selected_revision_id,
            limit=context_limit,
        )
        operations, total_operation_count = self._operations(
            selected_revision_id,
            limit=operation_limit,
        )
        history = self._history(selected_revision_id, limit=history_limit)
        policy = self.policies.get(
            project,
            branch,
            revision_id=selected_revision_id,
        )

        result: dict[str, Any] = {
            "format": RESUME_SNAPSHOT_FORMAT,
            "project": project,
            "branch": branch,
            "branch_head_revision_id": branch_head_revision_id,
            "revision_id": selected_revision_id,
            "revision_is_branch_head": (
                selected_revision_id == branch_head_revision_id
            ),
            "revision": revision,
            "limits": {
                "document_limit": document_limit,
                "target_limit": target_limit,
                "target_source_limit": target_source_limit,
                "context_limit": context_limit,
                "branch_limit": branch_limit,
                "history_limit": history_limit,
                "operation_limit": operation_limit,
            },
            "program_document_count": total_program_count,
            "returned_program_document_count": len(program_entries),
            "program_documents_truncated": (
                len(program_entries) < total_program_count
            ),
            "program_documents": program_entries,
            "build_target_count": total_target_count,
            "returned_build_target_count": len(target_entries),
            "build_targets_truncated": len(target_entries) < total_target_count,
            "build_targets": target_entries,
            "merge_policy": policy,
            "context_count": total_context_count,
            "returned_context_count": len(contexts),
            "contexts_truncated": len(contexts) < total_context_count,
            "contexts": contexts,
            "operation_count": total_operation_count,
            "returned_operation_count": len(operations),
            "operations_truncated": len(operations) < total_operation_count,
            "operations": operations,
            "history": history,
            "branch_count": total_branch_count,
            "returned_branch_count": len(branch_entries),
            "branches_truncated": len(branch_entries) < total_branch_count,
            "branches": branch_entries,
            "reproducible_fork": {
                "tool": "branch_create_at_revision",
                "arguments": {
                    "project": project,
                    "revision_id": selected_revision_id,
                },
                "required_argument_not_filled": "branch",
            },
            "build_recovery": {
                "tool": "build_list_page",
                "arguments": {
                    "project": project,
                    "revision_id": selected_revision_id,
                },
                "ordering_note": (
                    "build discovery is lexical by content-derived build ID, "
                    "not chronological"
                ),
            },
        }
        result["snapshot_id"] = self._snapshot_id(result)
        return result

    def _revision(self, project: str, revision_id: str) -> dict[str, Any]:
        row = self.workspace.db.connection.execute(
            """SELECT r.id, r.parent1_id, r.parent2_id, r.message, r.author,
                      r.root_hash, r.created_at
               FROM revisions r
               JOIN projects p ON p.id = r.project_id
               WHERE r.id = ? AND p.name = ?""",
            (revision_id, project),
        ).fetchone()
        if row is None:
            raise NotFoundError(
                f"revision {revision_id!r} does not belong to project {project!r}"
            )
        return dict(row)

    def _revision_modules(self, revision_id: str) -> dict[str, dict[str, Any]]:
        """Load one exact revision through the workspace semantic integrity boundary."""

        return self.workspace._state_at_revision(revision_id)

    def _program_document_names(
        self,
        modules: dict[str, dict[str, Any]],
    ) -> list[str]:
        return sorted(
            name
            for name in modules
            if not name.startswith(BUILD_TARGET_PREFIX)
        )

    def _programs(
        self,
        modules: dict[str, dict[str, Any]],
        revision_id: str,
        *,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        names = self._program_document_names(modules)
        page = names[:limit]
        return (
            [
                self._program_summary(
                    name,
                    modules[name],
                    revision_id=revision_id,
                )
                for name in page
            ],
            len(names),
        )

    def _targets(
        self,
        modules: dict[str, dict[str, Any]],
        revision_id: str,
        *,
        limit: int,
        source_limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        names = sorted(
            name for name in modules if name.startswith(BUILD_TARGET_PREFIX)
        )
        page = names[:limit]
        result: list[dict[str, Any]] = []
        for storage_document in page:
            name = storage_document[len(BUILD_TARGET_PREFIX) :]
            root = modules[storage_document]
            config = self.targets._parse_tree(root, name=name)
            documents = [config["document"], *config["additional_documents"]]
            self._require_program_documents(modules, documents)
            additional = list(config["additional_documents"])
            returned_additional = additional[:source_limit]
            result.append(
                {
                    "name": config["name"],
                    "document": config["document"],
                    "additional_document_count": len(additional),
                    "returned_additional_document_count": len(returned_additional),
                    "additional_documents_truncated": (
                        len(returned_additional) < len(additional)
                    ),
                    "additional_documents": returned_additional,
                    "compiler_target": config["compiler_target"],
                    "root_node_id": root["id"],
                }
            )
        return result, len(names)

    def _require_program_documents(
        self,
        modules: dict[str, dict[str, Any]],
        documents: list[str],
    ) -> None:
        for document in documents:
            if document not in modules or document.startswith(BUILD_TARGET_PREFIX):
                raise NotFoundError(f"program document {document!r} not found")

    def _branches(
        self,
        project: str,
        *,
        limit: int,
    ) -> tuple[list[dict[str, str]], int]:
        project_id = self.workspace.project_id(project)
        total = int(
            self.workspace.db.connection.execute(
                "SELECT COUNT(*) AS count FROM branches WHERE project_id = ?",
                (project_id,),
            ).fetchone()["count"]
        )
        rows = self.workspace.db.connection.execute(
            """SELECT name, head_revision_id FROM branches
               WHERE project_id = ? ORDER BY name LIMIT ?""",
            (project_id, limit),
        ).fetchall()
        return ([dict(row) for row in rows], total)

    @staticmethod
    def _program_summary(
        document: str,
        root: dict[str, Any],
        *,
        revision_id: str,
    ) -> dict[str, Any]:
        source, node_map = render_with_node_map(
            root,
            revision_id=revision_id,
            document=document,
        )
        return {
            "document": document,
            "root_node_id": root["id"],
            "head": head_symbol(root),
            "node_count": sum(1 for _ in walk_nodes(root)),
            "source_sha256": node_map["source_sha256"],
            "source_bytes": len(source.encode("utf-8")),
        }

    def _contexts(
        self,
        revision_id: str,
        *,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        total = int(
            self.workspace.db.connection.execute(
                """SELECT COUNT(*) AS count
                   FROM revision_documents WHERE revision_id = ?""",
                (revision_id,),
            ).fetchone()["count"]
        )
        rows = self.workspace.db.connection.execute(
            """SELECT d.id, d.scope_kind, d.scope_name, d.title, d.body,
                      d.content_hash
               FROM revision_documents rd
               JOIN documents d ON d.id = rd.document_id
               WHERE rd.revision_id = ?
               ORDER BY d.scope_kind, d.scope_name, d.title, d.id
               LIMIT ?""",
            (revision_id, limit),
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            body = str(row["body"])
            preview = body[:MAX_CONTEXT_PREVIEW_CHARS]
            result.append(
                {
                    "document_id": str(row["id"]),
                    "scope_kind": str(row["scope_kind"]),
                    "scope_name": str(row["scope_name"]),
                    "title": str(row["title"]),
                    "content_hash": str(row["content_hash"]),
                    "body_bytes": len(body.encode("utf-8")),
                    "body_preview": preview,
                    "body_truncated": len(preview) < len(body),
                }
            )
        return result, total

    def _operations(
        self,
        revision_id: str,
        *,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        total = int(
            self.workspace.db.connection.execute(
                "SELECT COUNT(*) AS count FROM operations WHERE revision_id = ?",
                (revision_id,),
            ).fetchone()["count"]
        )
        rows = self.workspace.db.connection.execute(
            """SELECT sequence_number, operation_kind, target, payload_json
               FROM operations
               WHERE revision_id = ?
               ORDER BY sequence_number
               LIMIT ?""",
            (revision_id, limit),
        ).fetchall()
        return (
            [
                {
                    "sequence_number": int(row["sequence_number"]),
                    "operation_kind": str(row["operation_kind"]),
                    "target": row["target"],
                    "payload": json.loads(str(row["payload_json"])),
                }
                for row in rows
            ],
            total,
        )

    def _history(self, revision_id: str, *, limit: int) -> dict[str, Any]:
        entries: list[dict[str, Any]] = []
        current: str | None = revision_id
        while current is not None and len(entries) < limit:
            row = self.workspace.db.connection.execute(
                """SELECT id, parent1_id, parent2_id, message, author,
                          root_hash, created_at
                   FROM revisions WHERE id = ?""",
                (current,),
            ).fetchone()
            if row is None:
                break
            entries.append(dict(row))
            current = row["parent1_id"]
        return {
            "returned_count": len(entries),
            "has_more": current is not None,
            "next_revision_id": current,
            "revisions": entries,
        }

    @staticmethod
    def _snapshot_id(result: dict[str, Any]) -> str:
        payload = json.dumps(
            result,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _validate_limit(name: str, value: int, maximum: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationError(
                "INVALID_RESUME_SNAPSHOT_LIMIT",
                f"{name} must be an integer",
            )
        if value < 1 or value > maximum:
            raise ValidationError(
                "INVALID_RESUME_SNAPSHOT_LIMIT",
                f"{name} must be between 1 and {maximum}",
            )
