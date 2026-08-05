"""Bounded compiler execution for exact virtual merge candidates."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .compiler import (
    MAX_COMPILER_PROTOCOL_BYTES,
    CompilerFileTooLarge,
    RenderedSource,
    collect_build_diagnostics,
    read_bounded_json,
    validate_compiler_manifest,
)
from .errors import ArtifactIntegrityError, ValidationError
from .merge_candidate_build import (
    MERGE_CANDIDATE_BUILD_FORMAT,
    MERGE_CANDIDATE_BUILD_KEY_FORMAT,
)
from .merge_candidate_build import (
    MergeCandidateBuildService as _BaseMergeCandidateBuildService,
)
from .test_target_validation import validate_test_target_references


class MergeCandidateBuildService(_BaseMergeCandidateBuildService):
    """Retain virtual-candidate builds through the bounded compiler bridge."""

    def build_exact(
        self,
        candidate: dict[str, Any],
        state: dict[str, Any],
        build_target: str,
    ) -> dict[str, Any]:
        """Build one captured candidate with the output policy in its cache key."""

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
            "compiler_output_limit_bytes": self.compiler.max_output_bytes,
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
            self._execute(
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

        process = self.compiler._run_compiler(command)
        diagnostics, diagnostics_valid = collect_build_diagnostics(
            compiler_diagnostics_path,
            canonical_sources=[
                (item.source_path, item.node_map) for item in materialized
            ],
            returncode=process.returncode,
            timed_out=process.timed_out,
            output_limited=process.output_limited,
            stdout=process.stdout,
            stderr=process.stderr,
            compiler_output_limit_bytes=self.compiler.max_output_bytes,
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
            returncode=process.returncode,
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

        self.compiler._discard_oversized_protocol_file(compiler_manifest_path)
        self.compiler._discard_oversized_protocol_file(compiler_diagnostics_path)
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
            "compiler_output_limit_bytes": self.compiler.max_output_bytes,
            "requested_target": effective_target or "native",
            "compiler_target": (
                compiler_manifest.get("target")
                if compiler_manifest_valid and compiler_manifest is not None
                else None
            ),
            "command": self._relative_command(command, temporary_directory),
            "returncode": process.returncode,
            "timed_out": process.timed_out,
            "output_limited": process.output_limited,
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
        for field in ("timed_out", "output_limited"):
            if not isinstance(manifest.get(field), bool):
                raise ArtifactIntegrityError(
                    f"merge candidate build {field} flag is invalid"
                )
        output_limit = manifest.get("compiler_output_limit_bytes")
        if (
            isinstance(output_limit, bool)
            or not isinstance(output_limit, int)
            or output_limit <= 0
        ):
            raise ArtifactIntegrityError(
                "merge candidate compiler output limit is invalid"
            )

        subject = manifest.get("subject")
        if not isinstance(subject, dict):
            raise ArtifactIntegrityError("merge candidate build subject is invalid")
        state = self._reconstruct_subject_state(subject)
        target = self._target_from_state(
            state,
            manifest.get("build_target", {}).get("name"),
        )
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
            "compiler_output_limit_bytes": output_limit,
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
                raise ArtifactIntegrityError(
                    "successful candidate build return code is invalid"
                )
            if manifest["timed_out"] is not False:
                raise ArtifactIntegrityError(
                    "successful candidate build timeout flag is invalid"
                )
            if manifest["output_limited"] is not False:
                raise ArtifactIntegrityError(
                    "successful candidate build output-limit flag is invalid"
                )
            if manifest.get("compiler_diagnostics_protocol_valid") is not True:
                raise ArtifactIntegrityError(
                    "successful candidate diagnostics are invalid"
                )
            if manifest.get("compiler_manifest_protocol_valid") is not True:
                raise ArtifactIntegrityError(
                    "successful candidate compiler manifest is invalid"
                )
            if artifacts.get("executable") != "program":
                raise ArtifactIntegrityError("successful candidate executable is missing")

    @staticmethod
    def _read_manifest(path: Path) -> dict[str, Any]:
        try:
            value = read_bounded_json(
                path,
                max_bytes=MAX_COMPILER_PROTOCOL_BYTES,
            )
        except CompilerFileTooLarge as exc:
            raise ArtifactIntegrityError(str(exc)) from exc
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ArtifactIntegrityError(
                f"cannot read merge candidate build manifest: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise ArtifactIntegrityError(
                "merge candidate build manifest root must be an object"
            )
        return value


__all__ = ["MergeCandidateBuildService"]
