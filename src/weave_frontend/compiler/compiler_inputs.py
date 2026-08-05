"""Compiler input selection, rendering, and executable resolution."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import NotFoundError, ValidationError
from .revision_limits import MAX_BUILD_DOCUMENTS
from .source_map import render_with_node_map


@dataclass(frozen=True)
class RenderedSource:
    document: str
    source: str
    node_map: dict[str, Any]


@dataclass(frozen=True)
class MaterializedSource:
    document: str
    source_path: Path
    map_path: Path
    source_sha256: str
    node_map: dict[str, Any]


class CompilerInputMixin:
    """Shared input preparation methods for the native compiler bridge."""

    workspace: Any
    _configured_compiler: str | Path | None
    _compiler: Path | None
    _environment_fallback: bool

    @staticmethod
    def _ordered_documents(
        document: str,
        additional_documents: list[str] | None,
    ) -> list[str]:
        values: list[Any] = [document]
        if additional_documents is not None:
            if not isinstance(additional_documents, list):
                raise ValidationError(
                    "INVALID_DOCUMENT_SET",
                    "additional_documents must be a list of document names",
                )
            values.extend(additional_documents)
        if len(values) > MAX_BUILD_DOCUMENTS:
            raise ValidationError(
                "BUILD_DOCUMENT_LIMIT_EXCEEDED",
                f"one compiler invocation may include at most {MAX_BUILD_DOCUMENTS} documents",
            )
        if any(not isinstance(value, str) or not value for value in values):
            raise ValidationError(
                "INVALID_DOCUMENT_SET",
                "document names must be non-empty strings",
            )
        documents = [str(value) for value in values]
        if len(set(documents)) != len(documents):
            raise ValidationError(
                "DUPLICATE_BUILD_DOCUMENT",
                "a document may appear only once in one build",
            )
        return documents

    @staticmethod
    def _render_sources(
        state: dict[str, Any],
        documents: list[str],
        *,
        revision: str,
    ) -> list[RenderedSource]:
        rendered: list[RenderedSource] = []
        for document in documents:
            try:
                root = state[document]
            except KeyError as exc:
                raise NotFoundError(
                    f"document {document!r} not found in revision {revision!r}"
                ) from exc
            source, node_map = render_with_node_map(
                root,
                revision_id=revision,
                document=document,
            )
            rendered.append(RenderedSource(document, source, node_map))
        return rendered

    @classmethod
    def _materialize_sources(
        cls,
        rendered: list[RenderedSource],
        directory: Path,
    ) -> list[MaterializedSource]:
        source_directory = directory / "sources"
        map_directory = directory / "source-maps"
        source_directory.mkdir()
        map_directory.mkdir()
        materialized: list[MaterializedSource] = []
        for index, item in enumerate(rendered):
            filename = f"{index:03d}-{cls._safe_document_basename(item.document)}"
            source_path = source_directory / filename
            map_path = map_directory / f"{filename}.map.json"
            source_path.write_text(item.source, encoding="utf-8")
            cls._write_json(map_path, item.node_map)
            materialized.append(
                MaterializedSource(
                    document=item.document,
                    source_path=source_path,
                    map_path=map_path,
                    source_sha256=str(item.node_map["source_sha256"]),
                    node_map=item.node_map,
                )
            )
        return materialized

    @staticmethod
    def _safe_document_basename(document: str) -> str:
        basename = document.replace("\\", "/").rsplit("/", 1)[-1]
        safe = "".join(
            character
            if character.isalnum() or character in {".", "_", "-"}
            else "_"
            for character in basename
        )
        if not safe:
            safe = "source.weave"
        if not safe.endswith(".weave"):
            safe += ".weave"
        return safe

    def _compiler_path(self) -> Path:
        if self._compiler is None:
            self._compiler = self._resolve_compiler(self._configured_compiler)
        return self._compiler

    def _resolve_compiler(self, compiler: str | Path | None) -> Path:
        environment_fallback = getattr(self, "_environment_fallback", True)
        configured = compiler
        if configured is None and environment_fallback:
            configured = os.environ.get("WEAVEC_BIN")
        if configured is None:
            validator = getattr(self.workspace, "validator", None)
            configured = getattr(validator, "binary", None)
        if configured is None and environment_fallback:
            configured = shutil.which("weavec")
        if configured is None:
            raise ValidationError(
                "WEAVEC_NOT_FOUND",
                "weavec was not found; set WEAVEC_BIN or install it on PATH",
            )
        path = Path(configured).expanduser().resolve()
        if not path.is_file() or not os.access(path, os.X_OK):
            raise ValidationError(
                "WEAVEC_NOT_EXECUTABLE",
                f"weavec is not executable: {path}",
            )
        return path

    def _require_project_revision(self, project: str, revision_id: str) -> str:
        row = self.workspace.db.connection.execute(
            """SELECT r.root_hash
               FROM revisions r
               JOIN projects p ON p.id = r.project_id
               WHERE r.id = ? AND p.name = ?""",
            (revision_id, project),
        ).fetchone()
        if row is None:
            raise NotFoundError(
                f"revision {revision_id!r} does not belong to project {project!r}"
            )
        return str(row["root_hash"])
