"""Revision-pinned bridge from the program database to ``weavec build``."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .compiler_diagnostics import collect_build_diagnostics
from .errors import NotFoundError, ValidationError
from .source_map import render_with_node_map


BUILD_KEY_FORMAT = "weave-build-key-v3"


@dataclass(frozen=True)
class _RenderedSource:
    document: str
    source: str
    node_map: dict[str, Any]


@dataclass(frozen=True)
class _MaterializedSource:
    document: str
    source_path: Path
    map_path: Path
    source_sha256: str
    node_map: dict[str, Any]


class CompilerBridge:
    """Build immutable database revisions through the public compiler interface."""

    def __init__(
        self,
        workspace: Any,
        *,
        compiler: str | Path | None = None,
        build_root: str | Path | None = None,
        timeout_seconds: int = 120,
    ) -> None:
        self.workspace = workspace
        self._configured_compiler = compiler
        self._compiler: Path | None = None
        default_root = workspace.db.path.parent / ".weave-build"
        configured_root = build_root or os.environ.get("WEAVE_BUILD_ROOT")
        self.build_root = Path(configured_root or default_root).resolve()
        self.build_root.mkdir(parents=True, exist_ok=True)
        self.timeout_seconds = timeout_seconds

    def build(
        self,
        project: str,
        document: str,
        *,
        additional_documents: list[str] | None = None,
        branch: str = "main",
        revision_id: str | None = None,
        target: str | None = None,
    ) -> dict[str, Any]:
        """Build an ordered document set from one exact immutable revision.

        ``document`` is the primary source and remains the legacy single-document
        API. ``additional_documents`` are passed to ``weavec build`` in the exact
        order supplied after the primary document.
        """

        documents = self._ordered_documents(document, additional_documents)
        revision = revision_id or self.workspace.branch_head(project, branch)
        revision_hash = self._require_project_revision(project, revision)
        state = self.workspace._state_at_revision(revision)
        rendered_sources = self._render_sources(
            state,
            documents,
            revision=revision,
        )

        compiler = self._compiler_path()
        compiler_hash = self._sha256_file(compiler)
        cache_payload = {
            "format": BUILD_KEY_FORMAT,
            "revision_hash": revision_hash,
            "revision_id": revision,
            "documents": [
                {
                    "document": item.document,
                    "source_sha256": item.node_map["source_sha256"],
                }
                for item in rendered_sources
            ],
            "compiler_sha256": compiler_hash,
            "target": target or "native",
        }
        build_id = hashlib.sha256(
            json.dumps(cache_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:32]
        final_directory = self.build_root / build_id

        cached = self._read_successful_manifest(final_directory)
        if cached is not None:
            cached["cached"] = True
            return cached

        temporary_directory = Path(
            tempfile.mkdtemp(prefix=f".{build_id}-", dir=self.build_root)
        )
        materialized_sources = self._materialize_sources(
            rendered_sources,
            temporary_directory,
        )
        executable_path = temporary_directory / "program"
        compiler_manifest_path = temporary_directory / "compiler-manifest.json"
        compiler_diagnostics_path = temporary_directory / "compiler-diagnostics.json"
        diagnostics_path = temporary_directory / "diagnostics.json"
        manifest_path = temporary_directory / "manifest.json"

        command = [
            str(compiler),
            "build",
            *(str(item.source_path) for item in materialized_sources),
            "-o",
            str(executable_path),
            "--manifest-json",
            str(compiler_manifest_path),
            "--diagnostics-json",
            str(compiler_diagnostics_path),
        ]
        if target:
            command.extend(["--target", target])

        timed_out = False
        try:
            completed = subprocess.run(
                command,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
            returncode: int | None = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            returncode = None
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode(errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode(errors="replace")
            stderr += f"\nweavec build timed out after {exc.timeout} seconds\n"
        except OSError as exc:
            returncode = None
            stdout = ""
            stderr = f"weavec build could not start: {exc}\n"

        diagnostics, protocol_valid = collect_build_diagnostics(
            compiler_diagnostics_path,
            canonical_sources=[
                (item.source_path, item.node_map) for item in materialized_sources
            ],
            returncode=returncode,
            timed_out=timed_out,
            stdout=stdout,
            stderr=stderr,
        )

        status = (
            "succeeded"
            if returncode == 0 and executable_path.is_file() and protocol_valid
            else "failed"
        )
        if status == "failed":
            executable_path.unlink(missing_ok=True)

        if compiler_manifest_path.is_file():
            self._relativize_json_file(compiler_manifest_path, temporary_directory)
        if compiler_diagnostics_path.is_file() and protocol_valid:
            self._relativize_json_file(compiler_diagnostics_path, temporary_directory)
        self._write_json(diagnostics_path, diagnostics)

        artifact_hashes = self._artifact_hashes(
            materialized_sources,
            diagnostics_path=diagnostics_path,
            compiler_manifest_path=compiler_manifest_path,
            compiler_diagnostics_path=compiler_diagnostics_path,
            executable_path=executable_path,
            base=temporary_directory,
        )
        source_artifacts = [
            {
                "document": item.document,
                "source": str(item.source_path.relative_to(temporary_directory)),
                "node_map": str(item.map_path.relative_to(temporary_directory)),
                "source_sha256": item.source_sha256,
            }
            for item in materialized_sources
        ]
        primary = source_artifacts[0]
        manifest: dict[str, Any] = {
            "format": "weave-frontend-build-manifest-v2",
            "build_key_format": BUILD_KEY_FORMAT,
            "build_id": build_id,
            "status": status,
            "cached": False,
            "project": project,
            "branch": branch,
            "revision_id": revision,
            "revision_hash": revision_hash,
            "document": document,
            "documents": documents,
            "sources": source_artifacts,
            "source_sha256": primary["source_sha256"],
            "compiler": str(compiler),
            "compiler_sha256": compiler_hash,
            "compiler_diagnostics_protocol_valid": protocol_valid,
            "target": target or "native",
            "command": self._relative_command(command, temporary_directory),
            "returncode": returncode,
            "artifacts": {
                "source": primary["source"],
                "node_map": primary["node_map"],
                "sources": [item["source"] for item in source_artifacts],
                "node_maps": [item["node_map"] for item in source_artifacts],
                "diagnostics": "diagnostics.json",
                "compiler_manifest": (
                    "compiler-manifest.json" if compiler_manifest_path.is_file() else None
                ),
                "compiler_diagnostics": (
                    "compiler-diagnostics.json"
                    if compiler_diagnostics_path.is_file()
                    else None
                ),
                "executable": "program" if executable_path.is_file() else None,
            },
            "artifact_sha256": artifact_hashes,
        }
        self._write_json(manifest_path, manifest)
        self._publish_directory(temporary_directory, final_directory)
        return self.get(build_id)

    def get(self, build_id: str) -> dict[str, Any]:
        """Return a stored build manifest with absolute artifact paths."""

        valid = build_id and all(
            character in "0123456789abcdef" for character in build_id
        )
        if not valid:
            raise ValidationError("INVALID_BUILD_ID", "build ID must be hexadecimal")
        directory = self.build_root / build_id
        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file():
            raise NotFoundError(f"build {build_id!r} not found")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return self._with_artifact_paths(manifest, directory)

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
    ) -> list[_RenderedSource]:
        rendered: list[_RenderedSource] = []
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
            rendered.append(_RenderedSource(document, source, node_map))
        return rendered

    @classmethod
    def _materialize_sources(
        cls,
        rendered: list[_RenderedSource],
        directory: Path,
    ) -> list[_MaterializedSource]:
        source_directory = directory / "sources"
        map_directory = directory / "source-maps"
        source_directory.mkdir()
        map_directory.mkdir()
        materialized: list[_MaterializedSource] = []
        for index, item in enumerate(rendered):
            filename = f"{index:03d}-{cls._safe_document_basename(item.document)}"
            source_path = source_directory / filename
            map_path = map_directory / f"{filename}.map.json"
            source_path.write_text(item.source, encoding="utf-8")
            cls._write_json(map_path, item.node_map)
            materialized.append(
                _MaterializedSource(
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

    @classmethod
    def _artifact_hashes(
        cls,
        sources: list[_MaterializedSource],
        *,
        diagnostics_path: Path,
        compiler_manifest_path: Path,
        compiler_diagnostics_path: Path,
        executable_path: Path,
        base: Path,
    ) -> dict[str, str]:
        hashes: dict[str, str] = {}
        for item in sources:
            hashes[str(item.source_path.relative_to(base))] = cls._sha256_file(
                item.source_path
            )
            hashes[str(item.map_path.relative_to(base))] = cls._sha256_file(
                item.map_path
            )
        hashes["diagnostics.json"] = cls._sha256_file(diagnostics_path)
        if compiler_manifest_path.is_file():
            hashes["compiler-manifest.json"] = cls._sha256_file(
                compiler_manifest_path
            )
        if compiler_diagnostics_path.is_file():
            hashes["compiler-diagnostics.json"] = cls._sha256_file(
                compiler_diagnostics_path
            )
        if executable_path.is_file():
            hashes["program"] = cls._sha256_file(executable_path)
        return hashes

    def _compiler_path(self) -> Path:
        if self._compiler is None:
            self._compiler = self._resolve_compiler(self._configured_compiler)
        return self._compiler

    def _resolve_compiler(self, compiler: str | Path | None) -> Path:
        configured = compiler or os.environ.get("WEAVEC_BIN")
        if configured is None:
            validator = getattr(self.workspace, "validator", None)
            configured = getattr(validator, "binary", None)
        if configured is None:
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

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        path.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def _relativize_json_file(cls, path: Path, base: Path) -> None:
        value = json.loads(path.read_text(encoding="utf-8"))
        cls._write_json(path, cls._relativize_value(value, base))

    @classmethod
    def _relativize_value(cls, value: Any, base: Path) -> Any:
        if isinstance(value, str):
            prefix = str(base) + os.sep
            return value[len(prefix) :] if value.startswith(prefix) else value
        if isinstance(value, list):
            return [cls._relativize_value(item, base) for item in value]
        if isinstance(value, dict):
            return {
                key: cls._relativize_value(item, base)
                for key, item in value.items()
            }
        return value

    @classmethod
    def _relative_command(cls, command: list[str], base: Path) -> list[str]:
        return [str(cls._relativize_value(argument, base)) for argument in command]

    @classmethod
    def _with_artifact_paths(
        cls,
        manifest: dict[str, Any],
        directory: Path,
    ) -> dict[str, Any]:
        manifest["build_directory"] = str(directory)
        manifest["artifact_paths"] = cls._resolve_artifact_value(
            manifest["artifacts"],
            directory,
        )
        return manifest

    @classmethod
    def _resolve_artifact_value(cls, value: Any, directory: Path) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            return str(directory / value)
        if isinstance(value, list):
            return [cls._resolve_artifact_value(item, directory) for item in value]
        if isinstance(value, dict):
            return {
                key: cls._resolve_artifact_value(item, directory)
                for key, item in value.items()
            }
        raise TypeError(f"unsupported artifact manifest value: {type(value).__name__}")

    @classmethod
    def _read_successful_manifest(cls, directory: Path) -> dict[str, Any] | None:
        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file():
            return None
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifacts = manifest.get("artifacts", {})
        executable = artifacts.get("executable")
        compiler_diagnostics = artifacts.get("compiler_diagnostics")
        sources = artifacts.get("sources")
        node_maps = artifacts.get("node_maps")
        if manifest.get("status") != "succeeded" or not executable:
            return None
        if manifest.get("build_key_format") != BUILD_KEY_FORMAT:
            return None
        if manifest.get("compiler_diagnostics_protocol_valid") is not True:
            return None
        if not compiler_diagnostics:
            return None
        if not isinstance(sources, list) or not sources:
            return None
        if not isinstance(node_maps, list) or len(node_maps) != len(sources):
            return None
        required = [executable, compiler_diagnostics, *sources, *node_maps]
        if any(not isinstance(path, str) or not (directory / path).is_file() for path in required):
            return None
        return cls._with_artifact_paths(manifest, directory)

    @staticmethod
    def _publish_directory(temporary: Path, final: Path) -> None:
        if final.exists():
            shutil.rmtree(final)
        os.replace(temporary, final)
