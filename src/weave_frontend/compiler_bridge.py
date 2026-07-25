"""Revision-pinned bridge from the program database to ``weavec build``."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .errors import NotFoundError, ValidationError
from .source_map import render_with_node_map


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
        self.compiler = self._resolve_compiler(compiler)
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
        branch: str = "main",
        revision_id: str | None = None,
        target: str | None = None,
    ) -> dict[str, Any]:
        """Build one document from an exact revision and return its manifest."""

        revision = revision_id or self.workspace.branch_head(project, branch)
        self._require_project_revision(project, revision)
        state = self.workspace._state_at_revision(revision)
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
        compiler_hash = self._sha256_file(self.compiler)
        cache_payload = {
            "format": "weave-build-key-v1",
            "revision_id": revision,
            "document": document,
            "source_sha256": node_map["source_sha256"],
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
        source_path = temporary_directory / "program.weave"
        map_path = temporary_directory / "program.weave.map.json"
        executable_path = temporary_directory / "program"
        compiler_manifest_path = temporary_directory / "compiler-manifest.json"
        diagnostics_path = temporary_directory / "diagnostics.json"
        manifest_path = temporary_directory / "manifest.json"

        source_path.write_text(source, encoding="utf-8")
        self._write_json(map_path, node_map)

        command = [
            str(self.compiler),
            "build",
            str(source_path),
            "-o",
            str(executable_path),
            "--manifest-json",
            str(compiler_manifest_path),
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

        status = "succeeded" if returncode == 0 and executable_path.is_file() else "failed"
        if status == "failed":
            executable_path.unlink(missing_ok=True)

        diagnostics = {
            "format": "weave-build-diagnostics-v1",
            "returncode": returncode,
            "timed_out": timed_out,
            "stdout": stdout,
            "stderr": stderr,
            "entries": [],
        }
        self._write_json(diagnostics_path, diagnostics)

        artifact_hashes: dict[str, str] = {
            "program.weave": self._sha256_file(source_path),
            "program.weave.map.json": self._sha256_file(map_path),
            "diagnostics.json": self._sha256_file(diagnostics_path),
        }
        if compiler_manifest_path.is_file():
            artifact_hashes["compiler-manifest.json"] = self._sha256_file(
                compiler_manifest_path
            )
        if executable_path.is_file():
            artifact_hashes["program"] = self._sha256_file(executable_path)

        manifest: dict[str, Any] = {
            "format": "weave-frontend-build-manifest-v1",
            "build_id": build_id,
            "status": status,
            "cached": False,
            "project": project,
            "branch": branch,
            "revision_id": revision,
            "document": document,
            "source_sha256": node_map["source_sha256"],
            "compiler": str(self.compiler),
            "compiler_sha256": compiler_hash,
            "target": target or "native",
            "command": command,
            "returncode": returncode,
            "artifacts": {
                "source": "program.weave",
                "node_map": "program.weave.map.json",
                "diagnostics": "diagnostics.json",
                "compiler_manifest": (
                    "compiler-manifest.json" if compiler_manifest_path.is_file() else None
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

        if not build_id or any(character not in "0123456789abcdef" for character in build_id):
            raise ValidationError("INVALID_BUILD_ID", "build ID must be hexadecimal")
        directory = self.build_root / build_id
        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file():
            raise NotFoundError(f"build {build_id!r} not found")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["build_directory"] = str(directory)
        manifest["artifact_paths"] = {
            key: str(directory / relative) if relative else None
            for key, relative in manifest["artifacts"].items()
        }
        return manifest

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

    @staticmethod
    def _read_successful_manifest(directory: Path) -> dict[str, Any] | None:
        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file():
            return None
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        executable = manifest.get("artifacts", {}).get("executable")
        if manifest.get("status") != "succeeded" or not executable:
            return None
        if not (directory / executable).is_file():
            return None
        manifest["build_directory"] = str(directory)
        manifest["artifact_paths"] = {
            key: str(directory / relative) if relative else None
            for key, relative in manifest["artifacts"].items()
        }
        return manifest

    @staticmethod
    def _publish_directory(temporary: Path, final: Path) -> None:
        if final.exists():
            shutil.rmtree(final)
        os.replace(temporary, final)
