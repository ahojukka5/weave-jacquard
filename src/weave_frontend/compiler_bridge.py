"""Revision-pinned bridge from the program database to ``weavec build``."""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .compiler_artifacts import BUILD_KEY_FORMAT, CompilerArtifactMixin
from .compiler_diagnostics import collect_build_diagnostics
from .compiler_inputs import CompilerInputMixin, RenderedSource
from .compiler_manifest import validate_compiler_manifest
from .errors import NotFoundError, ValidationError


class CompilerBridge(CompilerArtifactMixin, CompilerInputMixin):
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
            self._canonical_cache_payload(cache_payload)
        ).hexdigest()[:32]
        final_directory = self.build_root / build_id

        cached = self._read_successful_manifest(
            final_directory,
            expected_build_id=build_id,
        )
        if cached is not None:
            cached["cached"] = True
            return cached

        temporary_directory = Path(
            tempfile.mkdtemp(prefix=f".{build_id}-", dir=self.build_root)
        )
        try:
            return self._execute_build(
                project=project,
                document=document,
                documents=documents,
                branch=branch,
                revision=revision,
                revision_hash=revision_hash,
                compiler=compiler,
                compiler_hash=compiler_hash,
                target=target,
                build_id=build_id,
                final_directory=final_directory,
                rendered_sources=rendered_sources,
                temporary_directory=temporary_directory,
            )
        finally:
            if os.path.lexists(temporary_directory):
                self._remove_path(temporary_directory)

    @staticmethod
    def _canonical_cache_payload(value: dict[str, Any]) -> bytes:
        import json

        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()

    def _execute_build(
        self,
        *,
        project: str,
        document: str,
        documents: list[str],
        branch: str,
        revision: str,
        revision_hash: str,
        compiler: Path,
        compiler_hash: str,
        target: str | None,
        build_id: str,
        final_directory: Path,
        rendered_sources: list[RenderedSource],
        temporary_directory: Path,
    ) -> dict[str, Any]:
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

        returncode, timed_out, stdout, stderr = self._run_compiler(command)
        diagnostics, diagnostics_valid = collect_build_diagnostics(
            compiler_diagnostics_path,
            canonical_sources=[
                (item.source_path, item.node_map) for item in materialized_sources
            ],
            returncode=returncode,
            timed_out=timed_out,
            stdout=stdout,
            stderr=stderr,
        )
        compiler_summary = diagnostics.get("compiler")
        diagnostics_status = (
            compiler_summary.get("status")
            if isinstance(compiler_summary, dict)
            else None
        )
        compiler_manifest, compiler_manifest_errors = validate_compiler_manifest(
            compiler_manifest_path,
            expected_sources=[item.source_path for item in materialized_sources],
            expected_output=executable_path,
            requested_target=target,
            returncode=returncode,
            diagnostics_status=diagnostics_status,
        )
        compiler_manifest_valid = not compiler_manifest_errors
        self._attach_compiler_manifest_diagnostics(
            diagnostics,
            compiler_manifest=compiler_manifest,
            errors=compiler_manifest_errors,
        )

        status = (
            "succeeded"
            if (
                returncode == 0
                and executable_path.is_file()
                and diagnostics_valid
                and compiler_manifest_valid
            )
            else "failed"
        )
        if status == "failed":
            executable_path.unlink(missing_ok=True)

        if compiler_manifest_path.is_file() and compiler_manifest_valid:
            self._relativize_json_file(compiler_manifest_path, temporary_directory)
        if compiler_diagnostics_path.is_file() and diagnostics_valid:
            self._relativize_json_file(compiler_diagnostics_path, temporary_directory)
        self._write_json(diagnostics_path, diagnostics)

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
        artifact_hashes = self._artifact_hashes(
            materialized_sources,
            diagnostics_path=diagnostics_path,
            compiler_manifest_path=compiler_manifest_path,
            compiler_diagnostics_path=compiler_diagnostics_path,
            executable_path=executable_path,
            base=temporary_directory,
        )
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
            "compiler_diagnostics_protocol_valid": diagnostics_valid,
            "compiler_manifest_protocol_valid": compiler_manifest_valid,
            "compiler_manifest_errors": list(compiler_manifest_errors),
            "target": target or "native",
            "compiler_target": (
                compiler_manifest.get("target")
                if compiler_manifest_valid and compiler_manifest is not None
                else None
            ),
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

    def _run_compiler(
        self,
        command: list[str],
    ) -> tuple[int | None, bool, str, str]:
        timed_out = False
        try:
            completed = subprocess.run(
                command,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
            return completed.returncode, timed_out, completed.stdout, completed.stderr
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode(errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode(errors="replace")
            stderr += f"\nweavec build timed out after {exc.timeout} seconds\n"
            return None, True, stdout, stderr
        except OSError as exc:
            return None, False, "", f"weavec build could not start: {exc}\n"

    @staticmethod
    def _attach_compiler_manifest_diagnostics(
        diagnostics: dict[str, Any],
        *,
        compiler_manifest: dict[str, Any] | None,
        errors: list[str],
    ) -> None:
        diagnostics["compiler_manifest"] = (
            {
                key: compiler_manifest.get(key)
                for key in ("format", "status", "phase", "target")
            }
            if compiler_manifest is not None
            else None
        )
        diagnostics["compiler_manifest_protocol_valid"] = not errors
        diagnostics["compiler_manifest_errors"] = list(errors)
        if errors:
            diagnostics["entries"].append(
                {
                    "code": "bridge.invalid-compiler-manifest",
                    "severity": "error",
                    "phase": "bridge",
                    "message": "weavec produced a missing or invalid build manifest",
                    "source": None,
                    "compiler_source": None,
                    "document": None,
                    "span_origin": "none",
                    "span": None,
                    "node_id": None,
                    "details": list(errors),
                }
            )

    def get(self, build_id: str) -> dict[str, Any]:
        """Return a verified stored build manifest with absolute artifact paths."""

        if not self._valid_build_id(build_id):
            raise ValidationError(
                "INVALID_BUILD_ID",
                "build ID must contain exactly 32 lowercase hexadecimal characters",
            )
        directory = self.build_root / build_id
        if not (directory / "manifest.json").is_file():
            raise NotFoundError(f"build {build_id!r} not found")
        manifest = self._read_verified_manifest(
            directory,
            expected_build_id=build_id,
        )
        return self._with_artifact_paths(manifest, directory)
