"""Content-derived native builds for exact in-memory merge candidates."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Protocol

from ..artifact_quarantine import quarantine_artifact_directory
from ..builds import BuildTargetRegistry
from ..compiler import (
    REQUIRED_DIAGNOSTICS_FORMAT,
    REQUIRED_MANIFEST_FORMAT,
    CompilerBridge,
)
from ..errors import ArtifactIntegrityError, ValidationError
from ..project_metadata import is_project_metadata_document
from ..sexpr import JsonObject
from ..source_map import render_with_node_map
from .preview import MergePreviewService

MERGE_CANDIDATE_BUILD_FORMAT = "weave-merge-candidate-build-v1"
MERGE_CANDIDATE_SUBJECT_FORMAT = "weave-merge-candidate-v1"
MERGE_CANDIDATE_BUILD_MANIFEST = "candidate-build-manifest.json"


class _Workspace(Protocol):
    db: Any


class MergeCandidateBuildService:
    """Build one exact merge candidate without publishing a branch revision."""

    def __init__(
        self,
        previews: MergePreviewService,
        targets: BuildTargetRegistry,
        compiler: CompilerBridge,
        *,
        build_root: Path | None = None,
    ) -> None:
        self.previews = previews
        self.targets = targets
        self.compiler = compiler
        self.workspace: _Workspace = previews.workspace
        default_root = compiler.build_root / "merge-candidates"
        self.build_root = (build_root or default_root).resolve()

    def build(
        self,
        project: str,
        target_branch: str,
        source_branch: str,
        build_target: str,
        *,
        preview_id: str | None = None,
    ) -> dict[str, Any]:
        candidate = self.previews.candidate(project, target_branch, source_branch)
        self._require_candidate(candidate, preview_id)
        state = candidate.get("_merged_state")
        if not isinstance(state, dict):
            raise ValidationError(
                "INVALID_MERGE_CANDIDATE",
                "clean merge preview did not retain an in-memory candidate state",
            )
        config = self._resolve_target(build_target, state)
        documents = [config["document"], *config["additional_documents"]]
        sources = self._sources(state, documents, candidate)
        compiler = self.compiler._require_compiler()
        compiler_sha256 = self.compiler._sha256_file(compiler)
        capability_registry = self.compiler._capability_registry(
            command="build",
            protocols=(REQUIRED_MANIFEST_FORMAT, REQUIRED_DIAGNOSTICS_FORMAT),
            target=config["compiler_target"],
        )
        capability_identity = capability_registry["_jacquard_identity"]
        build_id = self.workspace.db.hash_value(
            {
                "format": MERGE_CANDIDATE_BUILD_FORMAT,
                "preview_id": candidate["preview_id"],
                "merged_root_hash": candidate["merged_root_hash"],
                "build_target": {
                    key: config[key]
                    for key in (
                        "name",
                        "document",
                        "additional_documents",
                        "compiler_target",
                        "evidence_profile",
                    )
                },
                "sources": [
                    {
                        "document": item["document"],
                        "source_sha256": item["source_sha256"],
                    }
                    for item in sources
                ],
                "compiler_sha256": compiler_sha256,
                "compiler_capabilities": capability_identity,
                "host_platform": self.compiler._host_platform_identity(),
            }
        )
        target_directory = self._directory(build_id)
        if target_directory.exists():
            try:
                cached = self.get(build_id)
            except (ArtifactIntegrityError, ValidationError, OSError, ValueError) as exc:
                quarantine_artifact_directory(
                    target_directory,
                    build_id=build_id,
                    reason=f"merge-candidate cache validation failed: {exc}",
                )
            else:
                cached["cached"] = True
                return cached

        target_directory.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(
            tempfile.mkdtemp(prefix=f".{build_id}.tmp-", dir=target_directory.parent)
        )
        try:
            result = self._compile(
                temporary,
                project=project,
                target_branch=target_branch,
                source_branch=source_branch,
                candidate=candidate,
                config=config,
                sources=sources,
                compiler=compiler,
                compiler_sha256=compiler_sha256,
                capability_identity=capability_identity,
                build_id=build_id,
            )
            if target_directory.exists():
                shutil.rmtree(temporary, ignore_errors=True)
                cached = self.get(build_id)
                cached["cached"] = True
                return cached
            os.replace(temporary, target_directory)
            result = self.get(build_id)
            result["cached"] = False
            return result
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    def get(self, build_id: str) -> dict[str, Any]:
        self.compiler._validate_build_id(build_id)
        directory = self._directory(build_id)
        path = directory / MERGE_CANDIDATE_BUILD_MANIFEST
        if not path.is_file():
            raise ValidationError(
                "MERGE_CANDIDATE_BUILD_NOT_FOUND",
                f"merge candidate build {build_id!r} was not found",
            )
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ArtifactIntegrityError(
                f"merge candidate build {build_id!r} has an unreadable manifest"
            ) from exc
        self._verify(manifest, directory, build_id)
        return manifest

    def _compile(
        self,
        directory: Path,
        *,
        project: str,
        target_branch: str,
        source_branch: str,
        candidate: dict[str, Any],
        config: dict[str, Any],
        sources: list[dict[str, Any]],
        compiler: Path,
        compiler_sha256: str,
        capability_identity: dict[str, Any],
        build_id: str,
    ) -> dict[str, Any]:
        source_directory = directory / "sources"
        source_directory.mkdir(parents=True, exist_ok=True)
        source_paths: list[Path] = []
        for index, item in enumerate(sources):
            path = source_directory / self.compiler._source_filename(
                index, str(item["document"])
            )
            path.write_text(str(item["source"]), encoding="utf-8")
            source_paths.append(path)

        executable = directory / "program"
        manifest_path = directory / "compiler-manifest.json"
        diagnostics_path = directory / "compiler-diagnostics.json"
        command = [str(compiler), "--build"]
        command.extend(str(path) for path in source_paths)
        command.extend(
            [
                "-o",
                str(executable),
                "--manifest-json",
                str(manifest_path),
                "--diagnostics-json",
                str(diagnostics_path),
            ]
        )
        if config["compiler_target"] != "native":
            command.extend(["--target", str(config["compiler_target"])])
        host = self.compiler._host_platform_identity()
        started_ns = self.compiler._monotonic_ns()
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=self.compiler.timeout_seconds,
        )
        finished_ns = self.compiler._monotonic_ns()
        if completed.returncode != 0:
            raise ValidationError(
                "MERGE_CANDIDATE_BUILD_FAILED",
                completed.stderr or completed.stdout or "weavec build failed",
            )
        if not executable.is_file():
            raise ArtifactIntegrityError("weavec succeeded without writing an executable")
        compiler_manifest = self.compiler._load_required_json(
            manifest_path,
            artifact="build manifest",
        )
        diagnostics = self.compiler._load_required_json(
            diagnostics_path,
            artifact="diagnostics",
        )
        self.compiler._validate_weavec_manifest(
            compiler_manifest,
            capability_registry={
                "formats": [REQUIRED_MANIFEST_FORMAT, REQUIRED_DIAGNOSTICS_FORMAT],
                "protocols": [REQUIRED_MANIFEST_FORMAT, REQUIRED_DIAGNOSTICS_FORMAT],
                "targets": [config["compiler_target"]],
            },
            expected_sources=source_paths,
            expected_output=executable,
            expected_target=config["compiler_target"],
        )
        self.compiler._validate_weavec_diagnostics(
            diagnostics,
            capability_registry={
                "formats": [REQUIRED_MANIFEST_FORMAT, REQUIRED_DIAGNOSTICS_FORMAT],
                "protocols": [REQUIRED_MANIFEST_FORMAT, REQUIRED_DIAGNOSTICS_FORMAT],
                "targets": [config["compiler_target"]],
            },
        )
        executable_sha256 = self.compiler._sha256_file(executable)
        artifact_paths = {
            "executable": str(executable),
            "compiler_manifest": str(manifest_path),
            "compiler_diagnostics": str(diagnostics_path),
        }
        artifact_sha256 = {
            "executable": executable_sha256,
            "compiler_manifest": self.compiler._sha256_file(manifest_path),
            "compiler_diagnostics": self.compiler._sha256_file(diagnostics_path),
        }
        compiler_stdout = completed.stdout or ""
        compiler_stderr = completed.stderr or ""
        subject = {
            "format": MERGE_CANDIDATE_SUBJECT_FORMAT,
            "committed_revision_id": None,
            "preview_id": candidate["preview_id"],
            "base_revision_id": candidate["base_revision_id"],
            "target_head_revision_id": candidate["target_head_revision_id"],
            "source_head_revision_id": candidate["source_head_revision_id"],
            "merged_root_hash": candidate["merged_root_hash"],
        }
        manifest = {
            "format": MERGE_CANDIDATE_BUILD_FORMAT,
            "build_id": build_id,
            "cached": False,
            "status": "succeeded",
            "project": project,
            "target_branch": target_branch,
            "source_branch": source_branch,
            "subject": subject,
            "build_target": {
                key: config[key]
                for key in (
                    "name",
                    "document",
                    "additional_documents",
                    "compiler_target",
                    "evidence_profile",
                )
            },
            "sources": [
                {
                    key: item[key]
                    for key in ("document", "root_node_id", "source_sha256")
                }
                for item in sources
            ],
            "compiler": {
                "path": str(compiler),
                "sha256": compiler_sha256,
                "capabilities": capability_identity,
            },
            "host_platform": host,
            "compiler_command": [
                self.compiler._relativize(path, directory) for path in command
            ],
            "compiler_returncode": completed.returncode,
            "compiler_stdout": compiler_stdout,
            "compiler_stderr": compiler_stderr,
            "duration_ms": max(0, (finished_ns - started_ns) // 1_000_000),
            "artifact_paths": {
                key: self.compiler._relativize(Path(value), directory)
                for key, value in artifact_paths.items()
            },
            "artifact_sha256": artifact_sha256,
            "artifact_sizes": {
                key: (directory / manifest_path_value).stat().st_size
                for key, manifest_path_value in {
                    key: self.compiler._relativize(Path(value), directory)
                    for key, value in artifact_paths.items()
                }.items()
            },
        }
        (directory / MERGE_CANDIDATE_BUILD_MANIFEST).write_text(
            self.compiler._canonical_json(manifest) + "\n",
            encoding="utf-8",
        )
        return manifest

    def _sources(
        self,
        state: dict[str, JsonObject],
        documents: list[str],
        candidate: dict[str, Any],
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for document in documents:
            if is_project_metadata_document(document):
                raise ValidationError(
                    "INVALID_BUILD_DOCUMENT",
                    "reserved project metadata cannot be compiled as source",
                )
            try:
                root = state[document]
            except KeyError as exc:
                raise ValidationError(
                    "INVALID_BUILD_DOCUMENT",
                    f"program document {document!r} is missing from the merge candidate",
                ) from exc
            source, node_map = render_with_node_map(
                root,
                revision_id=str(candidate["target_head_revision_id"]),
                document=document,
            )
            result.append(
                {
                    "document": document,
                    "root_node_id": str(root["id"]),
                    "source": source,
                    "source_sha256": str(node_map["source_sha256"]),
                }
            )
        return result

    def _resolve_target(
        self,
        name: str,
        state: dict[str, JsonObject],
    ) -> dict[str, Any]:
        target_name = self.targets._validate_name(name)
        storage_document = self.targets._storage_document(target_name)
        try:
            root = state[storage_document]
        except KeyError as exc:
            raise ValidationError(
                "MERGE_CANDIDATE_BUILD_TARGET_NOT_FOUND",
                f"build target {target_name!r} not found in the merge candidate",
            ) from exc
        config = self.targets._parse_tree(root, name=target_name)
        documents = [config["document"], *config["additional_documents"]]
        self.targets._require_program_documents(state, documents)
        return config

    @staticmethod
    def _require_candidate(
        candidate: dict[str, Any],
        preview_id: str | None,
    ) -> None:
        if preview_id is not None and (
            not isinstance(preview_id, str) or not preview_id
        ):
            raise ValidationError(
                "INVALID_MERGE_PREVIEW_ID",
                "preview_id must be a non-empty string",
            )
        if preview_id is not None and preview_id != candidate["preview_id"]:
            raise ValidationError(
                "STALE_MERGE_PREVIEW",
                "one or both branch heads changed after the merge preview",
            )
        if not candidate["mergeable"]:
            raise ValidationError(
                "MERGE_CANDIDATE_CONFLICT",
                "merge candidate is not buildable because the preview has conflicts",
            )

    def _directory(self, build_id: str) -> Path:
        return self.build_root / build_id[:2] / build_id

    def _verify(
        self,
        manifest: dict[str, Any],
        directory: Path,
        build_id: str,
    ) -> None:
        if manifest.get("format") != MERGE_CANDIDATE_BUILD_FORMAT:
            raise ArtifactIntegrityError("merge candidate build format mismatch")
        if manifest.get("build_id") != build_id:
            raise ArtifactIntegrityError("merge candidate build ID mismatch")
        subject = manifest.get("subject")
        if not isinstance(subject, dict):
            raise ArtifactIntegrityError("merge candidate build subject is missing")
        if subject.get("format") != MERGE_CANDIDATE_SUBJECT_FORMAT:
            raise ArtifactIntegrityError("merge candidate subject format mismatch")
        if subject.get("committed_revision_id") is not None:
            raise ArtifactIntegrityError(
                "merge candidate unexpectedly names a committed revision"
            )
        artifact_paths = manifest.get("artifact_paths")
        artifact_sha256 = manifest.get("artifact_sha256")
        artifact_sizes = manifest.get("artifact_sizes")
        if not isinstance(artifact_paths, dict) or not isinstance(artifact_sha256, dict):
            raise ArtifactIntegrityError("merge candidate artifact metadata is missing")
        if not isinstance(artifact_sizes, dict):
            raise ArtifactIntegrityError("merge candidate artifact sizes are missing")
        for key, relative in artifact_paths.items():
            if not isinstance(relative, str):
                raise ArtifactIntegrityError("merge candidate artifact path is invalid")
            path = (directory / relative).resolve()
            try:
                path.relative_to(directory.resolve())
            except ValueError as exc:
                raise ArtifactIntegrityError(
                    "merge candidate artifact escaped its build directory"
                ) from exc
            if not path.is_file():
                raise ArtifactIntegrityError(
                    f"merge candidate artifact {key!r} is missing"
                )
            expected = artifact_sha256.get(key)
            if expected != self.compiler._sha256_file(path):
                raise ArtifactIntegrityError(
                    f"merge candidate artifact {key!r} hash mismatch"
                )
            if artifact_sizes.get(key) != path.stat().st_size:
                raise ArtifactIntegrityError(
                    f"merge candidate artifact {key!r} size mismatch"
                )
        executable = (directory / str(artifact_paths["executable"])).resolve()
        if not executable.stat().st_mode & stat.S_IXUSR:
            raise ArtifactIntegrityError("merge candidate executable is not executable")
