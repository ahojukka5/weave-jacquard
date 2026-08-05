"""Revision-pinned bridge from the program database to ``weavec build``."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from ..bounded_process import BoundedProcessResult, run_bounded_process
from ..errors import NotFoundError, ValidationError
from .artifacts import CompilerArtifactMixin
from .capabilities import WeavecCapabilities
from .diagnostics import collect_build_diagnostics
from .evidence import (
    DEFAULT_EVIDENCE_PROFILE,
    normalize_evidence_profile,
    required_evidence_protocols,
)
from .inputs import CompilerInputMixin, RenderedSource
from .io import CompilerFileTooLarge, read_bounded_json
from .limits import (
    BUILD_KEY_FORMAT,
    MAX_COMPILER_OUTPUT_BYTES,
    MAX_COMPILER_PROTOCOL_BYTES,
)
from .manifest import validate_compiler_manifest


class CompilerBridge(CompilerArtifactMixin, CompilerInputMixin):
    """Build immutable database revisions through the public compiler interface."""

    def __init__(
        self,
        workspace: Any,
        *,
        compiler: str | Path | None = None,
        build_root: str | Path | None = None,
        capabilities: WeavecCapabilities | None = None,
        timeout_seconds: int = 120,
        max_output_bytes: int = MAX_COMPILER_OUTPUT_BYTES,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if isinstance(max_output_bytes, bool) or max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be a positive integer")
        self.workspace = workspace
        self._configured_compiler = compiler
        self._compiler: Path | None = None
        workspace_capabilities = getattr(workspace, "capabilities", None)
        self._capabilities = capabilities or (
            workspace_capabilities
            if isinstance(workspace_capabilities, WeavecCapabilities)
            else None
        )
        default_root = workspace.db.path.parent / ".weave-build"
        configured_root = build_root or os.environ.get("WEAVE_BUILD_ROOT")
        self.build_root = Path(configured_root or default_root).resolve()
        self.build_root.mkdir(parents=True, exist_ok=True)
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes

    def build(
        self,
        project: str,
        document: str,
        *,
        additional_documents: list[str] | None = None,
        branch: str = "main",
        revision_id: str | None = None,
        target: str | None = None,
        evidence_profile: str | None = None,
    ) -> dict[str, Any]:
        """Build an ordered document set from one exact immutable revision."""

        profile = normalize_evidence_profile(evidence_profile)
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
        self._require_evidence_profile(
            compiler,
            compiler_hash=compiler_hash,
            evidence_profile=profile,
            target=target,
        )
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
            "compiler_output_limit_bytes": self.max_output_bytes,
            "target": target or "native",
            "evidence_profile": profile,
        }
        build_id = hashlib.sha256(self._canonical_cache_payload(cache_payload)).hexdigest()[:32]
        final_directory = self.build_root / build_id

        cached = self._read_successful_manifest(
            final_directory,
            expected_build_id=build_id,
        )
        if cached is not None:
            cached["cached"] = True
            return cached

        temporary_directory = Path(tempfile.mkdtemp(prefix=f".{build_id}-", dir=self.build_root))
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
                evidence_profile=profile,
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
        evidence_profile: str,
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

        process = self._run_compiler(command)
        diagnostics, diagnostics_valid = collect_build_diagnostics(
            compiler_diagnostics_path,
            canonical_sources=[(item.source_path, item.node_map) for item in materialized_sources],
            returncode=process.returncode,
            timed_out=process.timed_out,
            output_limited=process.output_limited,
            stdout=process.stdout,
            stderr=process.stderr,
            compiler_output_limit_bytes=self.max_output_bytes,
        )
        compiler_summary = diagnostics.get("compiler")
        diagnostics_status = (
            compiler_summary.get("status") if isinstance(compiler_summary, dict) else None
        )
        compiler_manifest, compiler_manifest_errors = validate_compiler_manifest(
            compiler_manifest_path,
            expected_sources=[item.source_path for item in materialized_sources],
            expected_output=executable_path,
            requested_target=target,
            returncode=process.returncode,
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
                process.returncode == 0
                and not process.timed_out
                and not process.output_limited
                and executable_path.is_file()
                and diagnostics_valid
                and compiler_manifest_valid
            )
            else "failed"
        )
        if status == "failed":
            executable_path.unlink(missing_ok=True)

        self._discard_oversized_protocol_file(compiler_manifest_path)
        self._discard_oversized_protocol_file(compiler_diagnostics_path)
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
            "compiler_output_limit_bytes": self.max_output_bytes,
            "timed_out": process.timed_out,
            "output_limited": process.output_limited,
            "compiler_diagnostics_protocol_valid": diagnostics_valid,
            "compiler_manifest_protocol_valid": compiler_manifest_valid,
            "compiler_manifest_errors": list(compiler_manifest_errors),
            "target": target or "native",
            "evidence_profile": evidence_profile,
            "compiler_target": (
                compiler_manifest.get("target")
                if compiler_manifest_valid and compiler_manifest is not None
                else None
            ),
            "command": self._relative_command(command, temporary_directory),
            "returncode": process.returncode,
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
                    "compiler-diagnostics.json" if compiler_diagnostics_path.is_file() else None
                ),
                "executable": "program" if executable_path.is_file() else None,
            },
            "artifact_sha256": artifact_hashes,
        }
        self._write_json(manifest_path, manifest)
        self._publish_directory(temporary_directory, final_directory)
        return self.get(build_id)

    def _require_evidence_profile(
        self,
        compiler: Path,
        *,
        compiler_hash: str,
        evidence_profile: str,
        target: str | None,
    ) -> None:
        if evidence_profile == DEFAULT_EVIDENCE_PROFILE:
            return
        capabilities = self._capabilities
        if capabilities is None:
            capabilities = WeavecCapabilities(
                compiler,
                environment_fallback=False,
            )
            self._capabilities = capabilities
        document = capabilities.require(
            command="build",
            protocols=required_evidence_protocols(evidence_profile),
            target=target,
        )
        identity = document.get("_jacquard_identity")
        if not isinstance(identity, dict) or identity.get("compiler_sha256") != compiler_hash:
            raise ValidationError(
                "WEAVEC_CAPABILITY_COMPILER_MISMATCH",
                "compiler capability registry does not identify the selected build binary",
            )

    def _run_compiler(self, command: list[str]) -> BoundedProcessResult:
        try:
            result = run_bounded_process(
                command,
                timeout_seconds=self.timeout_seconds,
                max_output_bytes=self.max_output_bytes,
            )
        except OSError as exc:
            return BoundedProcessResult(
                returncode=None,
                timed_out=False,
                output_limited=False,
                stdout="",
                stderr=f"weavec build could not start: {exc}\n",
            )

        stderr = result.stderr
        if result.timed_out:
            stderr += f"\nweavec build timed out after {self.timeout_seconds} seconds\n"
        if result.output_limited:
            stderr += (
                "\nweavec build exceeded the combined stdout/stderr limit of "
                f"{self.max_output_bytes} bytes\n"
            )
        return BoundedProcessResult(
            returncode=(None if result.timed_out or result.output_limited else result.returncode),
            timed_out=result.timed_out,
            output_limited=result.output_limited,
            stdout=result.stdout,
            stderr=stderr,
        )

    @staticmethod
    def _discard_oversized_protocol_file(path: Path) -> None:
        try:
            oversized = path.is_file() and path.stat().st_size > MAX_COMPILER_PROTOCOL_BYTES
        except OSError:
            return
        if oversized:
            path.unlink(missing_ok=True)

    @staticmethod
    def _attach_compiler_manifest_diagnostics(
        diagnostics: dict[str, Any],
        *,
        compiler_manifest: dict[str, Any] | None,
        errors: list[str],
    ) -> None:
        diagnostics["compiler_manifest"] = (
            {key: compiler_manifest.get(key) for key in ("format", "status", "phase", "target")}
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

    @classmethod
    def _read_verified_manifest(
        cls,
        directory: Path,
        *,
        expected_build_id: str | None = None,
    ) -> dict[str, Any]:
        manifest = super()._read_verified_manifest(
            directory,
            expected_build_id=expected_build_id,
        )
        if manifest.get("build_key_format") == BUILD_KEY_FORMAT:
            cls._verify_current_policy(manifest, directory)
            cls._verify_current_build_key(manifest)
        return manifest

    @classmethod
    def _verify_current_policy(
        cls,
        manifest: dict[str, Any],
        directory: Path,
    ) -> None:
        output_limit = manifest.get("compiler_output_limit_bytes")
        if isinstance(output_limit, bool) or not isinstance(output_limit, int) or output_limit <= 0:
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                "compiler output limit must be a positive integer",
            )
        for field in ("timed_out", "output_limited"):
            if not isinstance(manifest.get(field), bool):
                raise ValidationError(
                    "INVALID_BUILD_MANIFEST",
                    f"build manifest {field} must be boolean",
                )
        if not isinstance(manifest.get("compiler_manifest_protocol_valid"), bool):
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                "compiler manifest protocol validity must be boolean",
            )
        if (manifest["timed_out"] or manifest["output_limited"]) and manifest.get(
            "returncode"
        ) is not None:
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                "limit-terminated compiler runs must have a null return code",
            )
        if manifest.get("status") == "succeeded" and (
            manifest.get("returncode") != 0
            or manifest["timed_out"]
            or manifest["output_limited"]
            or manifest.get("compiler_diagnostics_protocol_valid") is not True
            or manifest.get("compiler_manifest_protocol_valid") is not True
        ):
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                "successful build evidence disagrees with compiler termination policy",
            )

        diagnostics_relative = manifest.get("artifacts", {}).get("diagnostics")
        diagnostics_path = cls._artifact_path(directory, diagnostics_relative)
        if diagnostics_path is None:
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                "build diagnostics path is invalid",
            )
        try:
            diagnostics = read_bounded_json(
                diagnostics_path,
                max_bytes=MAX_COMPILER_PROTOCOL_BYTES,
            )
        except CompilerFileTooLarge as exc:
            raise ValidationError("INVALID_BUILD_MANIFEST", str(exc)) from exc
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                f"cannot read retained build diagnostics: {exc}",
            ) from exc
        if not isinstance(diagnostics, dict):
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                "retained build diagnostics root must be an object",
            )
        for field in ("timed_out", "output_limited"):
            if diagnostics.get(field) is not manifest.get(field):
                raise ValidationError(
                    "INVALID_BUILD_MANIFEST",
                    f"retained diagnostics {field} disagrees with build manifest",
                )
        if diagnostics.get("compiler_output_limit_bytes") != output_limit:
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                "retained diagnostics output limit disagrees with build manifest",
            )
        if diagnostics.get("protocol_valid") is not manifest.get(
            "compiler_diagnostics_protocol_valid"
        ):
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                "retained diagnostics protocol status disagrees with build manifest",
            )

    @classmethod
    def _verify_current_build_key(cls, manifest: dict[str, Any]) -> None:
        revision_hash = manifest.get("revision_hash")
        compiler_sha256 = manifest.get("compiler_sha256")
        revision_id = manifest.get("revision_id")
        target = manifest.get("target")
        if "evidence_profile" not in manifest:
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                "current build key requires an explicit evidence profile",
            )
        evidence_profile = normalize_evidence_profile(manifest["evidence_profile"])
        documents = manifest.get("documents")
        sources = manifest.get("sources")
        artifact_hashes = manifest.get("artifact_sha256")
        if not cls._valid_sha256(revision_hash) or not cls._valid_sha256(compiler_sha256):
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                "current build key requires revision and compiler SHA-256 values",
            )
        if not isinstance(revision_id, str) or not revision_id:
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                "current build key requires a revision ID",
            )
        if not isinstance(target, str) or not target:
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                "current build key requires a target",
            )
        if (
            not isinstance(documents, list)
            or not documents
            or any(not isinstance(item, str) or not item for item in documents)
        ):
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                "current build key requires ordered document names",
            )
        if not isinstance(sources, list) or len(sources) != len(documents):
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                "current build key requires one source record per document",
            )
        if not isinstance(artifact_hashes, dict):
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                "current build key requires artifact hashes",
            )

        key_documents: list[dict[str, str]] = []
        for index, (document, source) in enumerate(zip(documents, sources, strict=True)):
            if not isinstance(source, dict) or source.get("document") != document:
                raise ValidationError(
                    "INVALID_BUILD_MANIFEST",
                    f"source record {index} disagrees with document order",
                )
            relative = source.get("source")
            source_sha256 = source.get("source_sha256")
            if not isinstance(relative, str) or not relative:
                raise ValidationError(
                    "INVALID_BUILD_MANIFEST",
                    f"source record {index} has no artifact path",
                )
            if not cls._valid_sha256(source_sha256):
                raise ValidationError(
                    "INVALID_BUILD_MANIFEST",
                    f"source record {index} has an invalid SHA-256 value",
                )
            if artifact_hashes.get(relative) != source_sha256:
                raise ValidationError(
                    "INVALID_BUILD_MANIFEST",
                    f"source record {index} hash disagrees with artifact evidence",
                )
            key_documents.append({"document": document, "source_sha256": str(source_sha256)})
        if manifest.get("source_sha256") != key_documents[0]["source_sha256"]:
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                "primary source hash disagrees with ordered source evidence",
            )

        payload = {
            "format": BUILD_KEY_FORMAT,
            "revision_hash": revision_hash,
            "revision_id": revision_id,
            "documents": key_documents,
            "compiler_sha256": compiler_sha256,
            "compiler_output_limit_bytes": manifest["compiler_output_limit_bytes"],
            "target": target,
            "evidence_profile": evidence_profile,
        }
        expected_build_id = hashlib.sha256(cls._canonical_cache_payload(payload)).hexdigest()[:32]
        if manifest.get("build_id") != expected_build_id:
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                "bounded build inputs do not reproduce the stored build ID",
            )

    @classmethod
    def _read_successful_manifest(
        cls,
        directory: Path,
        *,
        expected_build_id: str | None = None,
    ) -> dict[str, Any] | None:
        if not (directory / "manifest.json").is_file():
            return None
        try:
            manifest = cls._read_verified_manifest(
                directory,
                expected_build_id=expected_build_id,
            )
            artifacts = manifest.get("artifacts")
            if not isinstance(artifacts, dict):
                return None
            sources = artifacts.get("sources")
            node_maps = artifacts.get("node_maps")
            if manifest.get("status") != "succeeded":
                return None
            if manifest.get("returncode") != 0:
                return None
            if manifest.get("build_key_format") != BUILD_KEY_FORMAT:
                return None
            if manifest.get("timed_out") is not False:
                return None
            if manifest.get("output_limited") is not False:
                return None
            if manifest.get("compiler_diagnostics_protocol_valid") is not True:
                return None
            if manifest.get("compiler_manifest_protocol_valid") is not True:
                return None
            if artifacts.get("executable") != "program":
                return None
            if artifacts.get("compiler_manifest") != "compiler-manifest.json":
                return None
            if artifacts.get("compiler_diagnostics") != "compiler-diagnostics.json":
                return None
            if not isinstance(sources, list) or not sources:
                return None
            if not isinstance(node_maps, list) or len(node_maps) != len(sources):
                return None
            return cls._with_artifact_paths(manifest, directory)
        except (ValidationError, TypeError):
            return None

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
