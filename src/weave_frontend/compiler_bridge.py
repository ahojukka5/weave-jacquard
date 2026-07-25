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

from .compiler_diagnostics import collect_build_diagnostics
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
        branch: str = "main",
        revision_id: str | None = None,
        target: str | None = None,
    ) -> dict[str, Any]:
        """Build one document from an exact revision and return its manifest."""

        revision = revision_id or self.workspace.branch_head(project, branch)
        revision_hash = self._require_project_revision(project, revision)
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
        compiler = self._compiler_path()
        compiler_hash = self._sha256_file(compiler)
        cache_payload = {
            "format": "weave-build-key-v1",
            "revision_hash": revision_hash,
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
        compiler_diagnostics_path = temporary_directory / "compiler-diagnostics.json"
        diagnostics_path = temporary_directory / "diagnostics.json"
        manifest_path = temporary_directory / "manifest.json"

        source_path.write_text(source, encoding="utf-8")
        self._write_json(map_path, node_map)

        command = [
            str(compiler),
            "build",
            str(source_path),
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
            node_map=node_map,
            canonical_source_path=source_path,
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
        if compiler_diagnostics_path.is_file():
            self._relativize_json_file(compiler_diagnostics_path, temporary_directory)
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
        if compiler_diagnostics_path.is_file():
            artifact_hashes["compiler-diagnostics.json"] = self._sha256_file(
                compiler_diagnostics_path
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
            "revision_hash": revision_hash,
            "document": document,
            "source_sha256": node_map["source_sha256"],
            "compiler": str(compiler),
            "compiler_sha256": compiler_hash,
            "compiler_diagnostics_protocol_valid": protocol_valid,
            "target": target or "native",
            "command": self._relative_command(command, temporary_directory),
            "returncode": returncode,
            "artifacts": {
                "source": "program.weave",
                "node_map": "program.weave.map.json",
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
        manifest["artifact_paths"] = {
            key: str(directory / relative) if relative else None
            for key, relative in manifest["artifacts"].items()
        }
        return manifest

    @classmethod
    def _read_successful_manifest(cls, directory: Path) -> dict[str, Any] | None:
        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file():
            return None
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        executable = manifest.get("artifacts", {}).get("executable")
        if manifest.get("status") != "succeeded" or not executable:
            return None
        if not (directory / executable).is_file():
            return None
        return cls._with_artifact_paths(manifest, directory)

    @staticmethod
    def _publish_directory(temporary: Path, final: Path) -> None:
        if final.exists():
            shutil.rmtree(final)
        os.replace(temporary, final)
