"""Verified compiler builds for exact uncommitted merge-candidate states."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .compiler_artifacts import CompilerArtifactMixin
from .compiler_diagnostics import collect_build_diagnostics
from .compiler_inputs import RenderedSource
from .compiler_manifest import validate_compiler_manifest
from .errors import ArtifactIntegrityError, ConflictError, NotFoundError, ValidationError
from .merge_preview import MERGE_PREVIEW_FORMAT
from .source_map import render_with_node_map
from .test_target_validation import validate_test_target_references

MERGE_CANDIDATE_BUILD_FORMAT = "weave-merge-candidate-build-manifest-v1"
MERGE_CANDIDATE_BUILD_KEY_FORMAT = "weave-merge-candidate-build-key-v1"
MERGE_CANDIDATE_NODE_MAP_FORMAT = "weave-merge-candidate-node-map-v1"
MERGE_CANDIDATE_BUILD_ID = re.compile(r"^[0-9a-f]{32}$")


class MergeCandidateBuildService(CompilerArtifactMixin):
    """Build and retain one named target from an exact virtual merge candidate."""

    def __init__(
        self,
        previews: Any,
        build_targets: Any,
        compiler: Any,
        *,
        build_root: str | Path | None = None,
    ) -> None:
        self.previews = previews
        self.workspace = previews.workspace
        self.build_targets = build_targets
        self.compiler = compiler
        configured = build_root or os.environ.get("WEAVE_MERGE_BUILD_ROOT")
        if configured is None:
            configured = Path(compiler.build_root) / "merge-candidates"
        self.build_root = Path(configured).resolve()
        self.build_root.mkdir(parents=True, exist_ok=True)

    def build(
        self,
        project: str,
        target_branch: str,
        source_branch: str,
        build_target: str,
        *,
        preview_id: str,
    ) -> dict[str, Any]:
        """Build one target after recreating and checking the exact current preview."""

        candidate = self._current_candidate(
            project,
            target_branch,
            source_branch,
            preview_id,
        )
        state = candidate.get("_merged_state")
        if not isinstance(state, dict):
            raise ValidationError(
                "INVALID_MERGE_CANDIDATE",
                "clean merge preview did not retain an in-memory candidate state",
            )
        return self.build_exact(candidate, state, build_target)

    def build_exact(
        self,
        candidate: dict[str, Any],
        state: dict[str, Any],
        build_target: str,
    ) -> dict[str, Any]:
        """Build a previously captured exact candidate without rereading branch heads."""

        subject = self._subject(candidate)
        if self.workspace.db.hash_value(state) != subject["merged_root_hash"]:
            raise ValidationError(
                "INVALID_MERGE_CANDIDATE",
                "captured candidate state does not match its merged root hash",
            )
        validate_test_target_references(state)
        target = self._target_from_state(state, build_target)
        documents = [target["document"], *target["additional_documents"]]
        rendered = self._render_candidate_sources(state, documents, subject)
        compiler_path = self.compiler._compiler_path()
        compiler_sha256 = self._sha256_file(compiler_path)
        effective_target = (
            None if target["compiler_target"] == "native" else target["compiler_target"]
        )
        input_document = {
            "format": MERGE_CANDIDATE_BUILD_KEY_FORMAT,
            "subject": subject,
            "build_target": {
                "name": target["name"],
                "definition_hash": target["definition_hash"],
                "document": target["document"],
                "additional_documents": target["additional_documents"],
                "compiler_target": target["compiler_target"],
            },
            "sources": [
                {
                    "document": item.document,
                    "source_sha256": item.node_map["source_sha256"],
                }
                for item in rendered
            ],
            "compiler_sha256": compiler_sha256,
            "requested_target": effective_target or "native",
        }
        build_input_hash = self._hash_json(input_document)
        build_id = build_input_hash[:32]
        final_directory = self.build_root / build_id
        cached = self._read_successful(final_directory, build_id)
        if cached is not None:
            cached["cached"] = True
            return cached

        temporary_directory = Path(
            tempfile.mkdtemp(prefix=f".{build_id}-", dir=self.build_root)
        )
        try:
            result = self._execute(
                subject=subject,
                target=target,
                documents=documents,
                rendered=rendered,
                compiler_path=compiler_path,
                compiler_sha256=compiler_sha256,
                effective_target=effective_target,
                build_id=build_id,
                build_input_hash=build_input_hash,
                temporary_directory=temporary_directory,
            )
            self._publish(temporary_directory, final_directory, build_id)
            return self.get(build_id)
        finally:
            if os.path.lexists(temporary_directory):
                self._remove_path(temporary_directory)

    def get(self, build_id: str) -> dict[str, Any]:
        """Read and verify one retained virtual-candidate build artifact."""

        if not isinstance(build_id, str) or not MERGE_CANDIDATE_BUILD_ID.fullmatch(
            build_id
        ):
            raise ValidationError(
                "INVALID_MERGE_CANDIDATE_BUILD_ID",
                "build_id must be 32 lowercase hexadecimal characters",
            )
        directory = (self.build_root / build_id).resolve()
        if directory.parent != self.build_root:
            raise ValidationError(
                "INVALID_MERGE_CANDIDATE_BUILD_ID",
                "build_id escapes merge candidate build root",
            )
        if not directory.is_dir():
            raise NotFoundError(f"merge candidate build {build_id!r} not found")
        manifest = self._read_manifest(directory / "manifest.json")
        self._verify_manifest(manifest, directory, expected_build_id=build_id)
        result = dict(manifest)
        result["artifact_paths"] = self._resolve_artifact_value(
            manifest["artifacts"], directory
        )
        result["build_directory"] = str(directory)
        result["manifest_sha256"] = self._sha256_file(directory / "manifest.json")
        return result

    def _execute(
        self,
        *,
        subject: dict[str, Any],
        target: dict[str, Any],
        documents: list[str],
        rendered: list[RenderedSource],
        compiler_path: Path,
        compiler_sha256: str,
        effective_target: str | None,
        build_id: str,
        build_input_hash: str,
        temporary_directory: Path,
    ) -> dict[str, Any]:
        materialized = self.compiler._materialize_sources(
            rendered,
            temporary_directory,
        )
        executable_path = temporary_directory / "program"
        compiler_manifest_path = temporary_directory / "compiler-manifest.json"
        compiler_diagnostics_path = temporary_directory / "compiler-diagnostics.json"
        diagnostics_path = temporary_directory / "diagnostics.json"
        command = [
            str(compiler_path),
            "build",
            *(str(item.source_path) for item in materialized),
            "-o",
            str(executable_path),
            "--manifest-json",
            str(compiler_manifest_path),
            "--diagnostics-json",
            str(compiler_diagnostics_path),
        ]
        if effective_target:
            command.extend(["--target", effective_target])

        returncode, timed_out, stdout, stderr = self.compiler._run_compiler(command)
        diagnostics, diagnostics_valid = collect_build_diagnostics(
            compiler_diagnostics_path,
            canonical_sources=[
                (item.source_path, item.node_map) for item in materialized
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
            expected_sources=[item.source_path for item in materialized],
            expected_output=executable_path,
            requested_target=effective_target,
            returncode=returncode,
            diagnostics_status=diagnostics_status,
        )
        compiler_manifest_valid = not compiler_manifest_errors
        self.compiler._attach_compiler_manifest_diagnostics(
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

        sources = [
            {
                "document": item.document,
                "source": str(item.source_path.relative_to(temporary_directory)),
                "node_map": str(item.map_path.relative_to(temporary_directory)),
                "source_sha256": item.source_sha256,
            }
            for item in materialized
        ]
        artifacts: dict[str, Any] = {
            "sources": [item["source"] for item in sources],
            "node_maps": [item["node_map"] for item in sources],
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
        }
        references = set(self._artifact_references(artifacts))
        artifact_sha256 = {
            relative: self._sha256_file(temporary_directory / relative)
            for relative in sorted(references)
        }
        manifest = {
            "format": MERGE_CANDIDATE_BUILD_FORMAT,
            "build_key_format": MERGE_CANDIDATE_BUILD_KEY_FORMAT,
            "build_id": build_id,
            "status": status,
            "cached": False,
            "subject": subject,
            "build_target": {
                "name": target["name"],
                "definition_hash": target["definition_hash"],
                "document": target["document"],
                "additional_documents": target["additional_documents"],
                "compiler_target": target["compiler_target"],
            },
            "documents": documents,
            "sources": sources,
            "compiler_sha256": compiler_sha256,
            "requested_target": effective_target or "native",
            "compiler_target": (
                compiler_manifest.get("target")
                if compiler_manifest_valid and compiler_manifest is not None
                else None
            ),
            "command": self._relative_command(command, temporary_directory),
            "returncode": returncode,
            "timed_out": timed_out,
            "compiler_diagnostics_protocol_valid": diagnostics_valid,
            "compiler_manifest_protocol_valid": compiler_manifest_valid,
            "compiler_manifest_errors": list(compiler_manifest_errors),
            "build_input_hash": build_input_hash,
            "artifacts": artifacts,
            "artifact_sha256": artifact_sha256,
        }
        self._write_json(temporary_directory / "manifest.json", manifest)
        self._verify_manifest(
            manifest,
            temporary_directory,
            expected_build_id=build_id,
        )
        return manifest

    def _verify_manifest(
        self,
        manifest: dict[str, Any],
        directory: Path,
        *,
        expected_build_id: str,
    ) -> None:
        if manifest.get("format") != MERGE_CANDIDATE_BUILD_FORMAT:
            raise ArtifactIntegrityError("merge candidate build manifest format is invalid")
        if manifest.get("build_id") != expected_build_id:
            raise ArtifactIntegrityError("merge candidate build identity is invalid")
        if manifest.get("status") not in {"succeeded", "failed"}:
            raise ArtifactIntegrityError("merge candidate build status is invalid")
        if manifest.get("build_key_format") != MERGE_CANDIDATE_BUILD_KEY_FORMAT:
            raise ArtifactIntegrityError("merge candidate build key format is invalid")
        subject = manifest.get("subject")
        if not isinstance(subject, dict):
            raise ArtifactIntegrityError("merge candidate build subject is invalid")
        state = self._reconstruct_subject_state(subject)
        target = self._target_from_state(state, manifest.get("build_target", {}).get("name"))
        recorded_target = manifest.get("build_target")
        expected_target = {
            "name": target["name"],
            "definition_hash": target["definition_hash"],
            "document": target["document"],
            "additional_documents": target["additional_documents"],
            "compiler_target": target["compiler_target"],
        }
        if recorded_target != expected_target:
            raise ArtifactIntegrityError("merge candidate build target evidence is invalid")
        documents = [target["document"], *target["additional_documents"]]
        if manifest.get("documents") != documents:
            raise ArtifactIntegrityError("merge candidate build document order is invalid")
        rendered = self._render_candidate_sources(state, documents, subject)
        expected_sources = [
            {
                "document": item.document,
                "source_sha256": item.node_map["source_sha256"],
            }
            for item in rendered
        ]
        recorded_sources = manifest.get("sources")
        if not isinstance(recorded_sources, list) or [
            {
                "document": item.get("document"),
                "source_sha256": item.get("source_sha256"),
            }
            for item in recorded_sources
        ] != expected_sources:
            raise ArtifactIntegrityError("merge candidate build source evidence is invalid")
        input_document = {
            "format": MERGE_CANDIDATE_BUILD_KEY_FORMAT,
            "subject": subject,
            "build_target": expected_target,
            "sources": expected_sources,
            "compiler_sha256": manifest.get("compiler_sha256"),
            "requested_target": manifest.get("requested_target"),
        }
        expected_input_hash = self._hash_json(input_document)
        if manifest.get("build_input_hash") != expected_input_hash:
            raise ArtifactIntegrityError("merge candidate build input hash is invalid")
        if expected_input_hash[:32] != expected_build_id:
            raise ArtifactIntegrityError("merge candidate build ID is not content derived")
        try:
            self._verify_artifacts(manifest, directory)
        except ValidationError as exc:
            raise ArtifactIntegrityError(str(exc)) from exc
        artifacts = manifest.get("artifacts", {})
        if manifest["status"] == "succeeded":
            if manifest.get("returncode") != 0:
                raise ArtifactIntegrityError("successful candidate build return code is invalid")
            if manifest.get("timed_out") is not False:
                raise ArtifactIntegrityError("successful candidate build timeout flag is invalid")
            if manifest.get("compiler_diagnostics_protocol_valid") is not True:
                raise ArtifactIntegrityError("successful candidate diagnostics are invalid")
            if manifest.get("compiler_manifest_protocol_valid") is not True:
                raise ArtifactIntegrityError("successful candidate compiler manifest is invalid")
            if artifacts.get("executable") != "program":
                raise ArtifactIntegrityError("successful candidate executable is missing")

    def _current_candidate(
        self,
        project: str,
        target_branch: str,
        source_branch: str,
        preview_id: str,
    ) -> dict[str, Any]:
        if not isinstance(preview_id, str) or not preview_id:
            raise ValidationError(
                "INVALID_MERGE_PREVIEW_ID",
                "preview_id must be a non-empty string",
            )
        candidate = self.previews.candidate(project, target_branch, source_branch)
        if candidate["preview_id"] != preview_id:
            raise ValidationError(
                "STALE_MERGE_PREVIEW",
                "one or both branch heads changed after the merge preview",
            )
        if not candidate["mergeable"]:
            raise ConflictError(list(candidate["conflicts"]))
        return candidate

    @staticmethod
    def _subject(candidate: dict[str, Any]) -> dict[str, Any]:
        return {
            "kind": "virtual_merge_candidate",
            "project": candidate["project"],
            "target_branch": candidate["target_branch"],
            "source_branch": candidate["source_branch"],
            "base_revision_id": candidate["base_revision_id"],
            "target_head_revision_id": candidate["target_head_revision_id"],
            "source_head_revision_id": candidate["source_head_revision_id"],
            "preview_id": candidate["preview_id"],
            "merged_root_hash": candidate["merged_root_hash"],
            "committed_revision_id": None,
        }

    def _reconstruct_subject_state(self, subject: dict[str, Any]) -> dict[str, Any]:
        required = {
            "kind",
            "project",
            "target_branch",
            "source_branch",
            "base_revision_id",
            "target_head_revision_id",
            "source_head_revision_id",
            "preview_id",
            "merged_root_hash",
            "committed_revision_id",
        }
        if set(subject) != required or subject.get("kind") != "virtual_merge_candidate":
            raise ArtifactIntegrityError("merge candidate build subject shape is invalid")
        if subject.get("committed_revision_id") is not None:
            raise ArtifactIntegrityError("virtual candidate cannot name a committed revision")
        project = subject["project"]
        base_revision = subject["base_revision_id"]
        target_revision = subject["target_head_revision_id"]
        source_revision = subject["source_head_revision_id"]
        for revision in (base_revision, target_revision, source_revision):
            self.compiler._require_project_revision(project, revision)
        if self.workspace._common_ancestor(target_revision, source_revision) != base_revision:
            raise ArtifactIntegrityError("merge candidate common base is invalid")
        preview_payload = {
            "format": MERGE_PREVIEW_FORMAT,
            "project": project,
            "target_branch": subject["target_branch"],
            "source_branch": subject["source_branch"],
            "base_revision_id": base_revision,
            "target_head_revision_id": target_revision,
            "source_head_revision_id": source_revision,
        }
        if self.workspace.db.hash_value(preview_payload) != subject["preview_id"]:
            raise ArtifactIntegrityError("merge candidate preview identity is invalid")
        base_state = self.workspace._state_at_revision(base_revision)
        target_state = self.workspace._state_at_revision(target_revision)
        source_state = self.workspace._state_at_revision(source_revision)
        try:
            state, _ = self.workspace._merge_states(
                base_state,
                target_state,
                source_state,
            )
            self.workspace._validate_state(state)
            validate_test_target_references(state)
        except Exception as exc:
            raise ArtifactIntegrityError(
                f"cannot reconstruct merge candidate state: {exc}"
            ) from exc
        if self.workspace.db.hash_value(state) != subject["merged_root_hash"]:
            raise ArtifactIntegrityError("merge candidate merged root hash is invalid")
        return state

    def _target_from_state(
        self,
        state: dict[str, Any],
        name: Any,
    ) -> dict[str, Any]:
        target_name = self.build_targets._validate_name(name)
        storage_document = self.build_targets._storage_document(target_name)
        try:
            root = state[storage_document]
        except KeyError as exc:
            raise NotFoundError(f"build target {target_name!r} not found") from exc
        config = self.build_targets._parse_tree(root, name=target_name)
        documents = [config["document"], *config["additional_documents"]]
        self.build_targets._require_program_documents(state, documents)
        return {
            **config,
            "definition_hash": self.workspace.db.hash_value(root),
        }

    def _render_candidate_sources(
        self,
        state: dict[str, Any],
        documents: list[str],
        subject: dict[str, Any],
    ) -> list[RenderedSource]:
        rendered: list[RenderedSource] = []
        for document in documents:
            try:
                root = state[document]
            except KeyError as exc:
                raise NotFoundError(
                    f"document {document!r} not found in merge candidate"
                ) from exc
            source, node_map = render_with_node_map(
                root,
                revision_id=f"virtual-merge:{subject['preview_id']}",
                document=document,
            )
            node_map["format"] = MERGE_CANDIDATE_NODE_MAP_FORMAT
            node_map["subject"] = {
                "kind": "virtual_merge_candidate",
                "preview_id": subject["preview_id"],
                "merged_root_hash": subject["merged_root_hash"],
                "committed_revision_id": None,
            }
            rendered.append(RenderedSource(document, source, node_map))
        return rendered

    def _publish(self, temporary: Path, final: Path, build_id: str) -> None:
        self._verify_manifest(
            self._read_manifest(temporary / "manifest.json"),
            temporary,
            expected_build_id=build_id,
        )
        with self._publication_lock(final):
            existing = self._read_successful(final, build_id)
            if existing is not None:
                self._remove_path(temporary)
                return
            if os.path.lexists(final):
                raise ArtifactIntegrityError(
                    f"merge candidate build {build_id!r} already exists but is invalid"
                )
            os.replace(temporary, final)

    def _read_successful(
        self,
        directory: Path,
        build_id: str,
    ) -> dict[str, Any] | None:
        if not (directory / "manifest.json").is_file():
            return None
        try:
            result = self.get(build_id)
        except (ArtifactIntegrityError, NotFoundError, ValidationError, TypeError):
            return None
        return result if result.get("status") == "succeeded" else None

    @staticmethod
    def _read_manifest(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ArtifactIntegrityError(
                f"cannot read merge candidate build manifest: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise ArtifactIntegrityError(
                "merge candidate build manifest root must be an object"
            )
        return value

    @staticmethod
    def _hash_json(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
