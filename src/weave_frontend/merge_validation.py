"""Authoritative compiler validation for exact in-memory merge candidates."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Protocol

from .build_targets import BuildTargetRegistry
from .errors import ConflictError, NotFoundError, ValidationError
from .merge_preview import MergePreviewService
from .sexpr import render_node

MERGE_VALIDATION_FORMAT = "weave-merge-validation-v1"
MAX_VALIDATION_OUTPUT_CHARACTERS = 8192


class _Validator(Protocol):
    def _active_binary(self) -> Path | None: ...

    def validate_sources(self, sources: list[tuple[str, str]]) -> dict[str, Any]: ...


class _Workspace(Protocol):
    db: Any
    validator: _Validator


class MergeValidationService:
    """Validate and gate one exact prospective merge through ``weavec``."""

    def __init__(
        self,
        workspace: _Workspace,
        previews: MergePreviewService,
        targets: BuildTargetRegistry,
    ) -> None:
        self.workspace = workspace
        self.previews = previews
        self.targets = targets

    def validate(
        self,
        project: str,
        target_branch: str,
        source_branch: str,
        build_target: str,
        *,
        preview_id: str | None = None,
    ) -> dict[str, Any]:
        """Validate one named target from the exact current merge candidate."""

        if preview_id is not None and (
            not isinstance(preview_id, str) or not preview_id
        ):
            raise ValidationError(
                "INVALID_MERGE_PREVIEW_ID",
                "preview_id must be a non-empty string",
            )

        candidate = self.previews.candidate(project, target_branch, source_branch)
        if preview_id is not None and preview_id != candidate["preview_id"]:
            raise ValidationError(
                "STALE_MERGE_PREVIEW",
                "one or both branch heads changed after the merge preview",
            )
        if not candidate["mergeable"]:
            raise ConflictError(list(candidate["conflicts"]))

        state = candidate.get("_merged_state")
        if not isinstance(state, dict):
            raise ValidationError(
                "INVALID_MERGE_CANDIDATE",
                "clean merge preview did not retain an in-memory candidate state",
            )
        config = self._resolve_target(build_target, state)
        documents = [config["document"], *config["additional_documents"]]

        sources: list[tuple[str, str]] = []
        source_records: list[dict[str, Any]] = []
        for document in documents:
            root = state[document]
            source = render_node(root) + "\n"
            source_bytes = source.encode("utf-8")
            source_hash = hashlib.sha256(source_bytes).hexdigest()
            sources.append((document, source))
            source_records.append(
                {
                    "document": document,
                    "root_node_id": str(root["id"]),
                    "source_sha256": source_hash,
                    "source_bytes": len(source_bytes),
                }
            )

        compiler = self._compiler_identity()
        validation_payload = {
            "format": MERGE_VALIDATION_FORMAT,
            "preview_id": candidate["preview_id"],
            "merged_root_hash": candidate["merged_root_hash"],
            "build_target": {
                key: config[key]
                for key in (
                    "name",
                    "document",
                    "additional_documents",
                    "compiler_target",
                )
            },
            "sources": [
                {
                    "document": item["document"],
                    "source_sha256": item["source_sha256"],
                }
                for item in source_records
            ],
            "compiler_sha256": compiler["sha256"],
        }
        validation_id = self.workspace.db.hash_value(validation_payload)
        raw = self.workspace.validator.validate_sources(sources)
        wir = raw.get("wir")
        wir_text = wir if isinstance(wir, str) else None
        stdout, stdout_truncated = self._bounded_text(raw.get("stdout"))
        stderr, stderr_truncated = self._bounded_text(raw.get("stderr"))

        return {
            "format": MERGE_VALIDATION_FORMAT,
            "validation_id": validation_id,
            "preview_id": candidate["preview_id"],
            "project": project,
            "target_branch": target_branch,
            "source_branch": source_branch,
            "base_revision_id": candidate["base_revision_id"],
            "target_head_revision_id": candidate["target_head_revision_id"],
            "source_head_revision_id": candidate["source_head_revision_id"],
            "merged_root_hash": candidate["merged_root_hash"],
            "build_target": validation_payload["build_target"],
            "documents": documents,
            "sources": source_records,
            "compiler": compiler,
            "available": raw.get("available"),
            "valid": raw.get("valid"),
            "returncode": raw.get("returncode"),
            "timed_out": bool(raw.get("timed_out", False)),
            "diagnostic": raw.get("diagnostic"),
            "stdout": stdout,
            "stdout_truncated": stdout_truncated,
            "stderr": stderr,
            "stderr_truncated": stderr_truncated,
            "wir_sha256": (
                hashlib.sha256(wir_text.encode("utf-8")).hexdigest()
                if wir_text is not None
                else None
            ),
            "wir_bytes": len(wir_text.encode("utf-8")) if wir_text is not None else 0,
        }

    @staticmethod
    def require_valid(result: dict[str, Any]) -> None:
        """Reject publication unless compiler validation was available and passed."""

        if result.get("available") is not True:
            raise ValidationError(
                "MERGE_VALIDATION_UNAVAILABLE",
                str(result.get("diagnostic") or "weavec validation is unavailable"),
            )
        if result.get("valid") is not True:
            diagnostic = result.get("diagnostic")
            stderr = result.get("stderr")
            message = diagnostic or stderr or "the prospective merge failed validation"
            raise ValidationError("MERGE_VALIDATION_FAILED", str(message))

    def _resolve_target(
        self,
        name: str,
        state: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        target_name = self.targets._validate_name(name)
        storage_document = self.targets._storage_document(target_name)
        try:
            root = state[storage_document]
        except KeyError as exc:
            raise NotFoundError(f"build target {target_name!r} not found") from exc
        config = self.targets._parse_tree(root, name=target_name)
        documents = [config["document"], *config["additional_documents"]]
        self.targets._require_program_documents(state, documents)
        return {
            **config,
            "storage_document": storage_document,
            "root_node_id": str(root["id"]),
        }

    def _compiler_identity(self) -> dict[str, Any]:
        binary = self.workspace.validator._active_binary()
        if binary is None:
            return {"available": False, "path": None, "sha256": None}
        digest = hashlib.sha256()
        with binary.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return {
            "available": True,
            "path": str(binary),
            "sha256": digest.hexdigest(),
        }

    @staticmethod
    def _bounded_text(value: Any) -> tuple[str, bool]:
        text = value if isinstance(value, str) else ""
        if len(text) <= MAX_VALIDATION_OUTPUT_CHARACTERS:
            return text, False
        return text[:MAX_VALIDATION_OUTPUT_CHARACTERS], True
