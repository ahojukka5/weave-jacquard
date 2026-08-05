"""Explicit sandboxed behavioral-test batches for exact virtual merge candidates."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any

from .compiler import CompilerArtifactMixin
from .errors import ArtifactIntegrityError, ConflictError, NotFoundError, ValidationError
from .retained_artifact_io import (
    RetainedArtifactReadError,
    read_bounded_regular_json,
)
from .sandbox import BubblewrapSandbox, SandboxBackend, SandboxLimits
from .test_targets import TEST_TARGET_NAME

MERGE_CANDIDATE_TEST_BATCH_FORMAT = "weave-merge-candidate-test-batch-v1"
MERGE_CANDIDATE_TEST_OUTPUT_PAGE_FORMAT = (
    "weave-merge-candidate-test-output-page-v1"
)
MERGE_CANDIDATE_TEST_BATCH_ID = re.compile(r"^[0-9a-f]{32}$")
MAX_MERGE_CANDIDATE_TEST_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_MERGE_CANDIDATE_TESTS = 64
DEFAULT_OUTPUT_PAGE_BYTES = 16_384
MAX_OUTPUT_PAGE_BYTES = 65_536


class MergeCandidateTestBatchService(CompilerArtifactMixin):
    """Build and run one caller-selected test set on an exact virtual candidate."""

    def __init__(
        self,
        previews: Any,
        tests: Any,
        builds: Any,
        sandbox: SandboxBackend | None = None,
        *,
        run_root: str | Path | None = None,
    ) -> None:
        self.previews = previews
        self.workspace = previews.workspace
        self.tests = tests
        self.builds = builds
        self.sandbox = sandbox or BubblewrapSandbox()
        configured = run_root or os.environ.get("WEAVE_MERGE_TEST_RUN_ROOT")
        if configured is None:
            configured = self.workspace.db.path.parent / ".weave-merge-test-runs"
        self.run_root = Path(configured).resolve()
        self.run_root.mkdir(parents=True, exist_ok=True)

    def capabilities(self) -> dict[str, Any]:
        """Return the strict sandbox policy used by candidate execution."""

        return self.sandbox.capabilities()

    def run(
        self,
        project: str,
        target_branch: str,
        source_branch: str,
        test_targets: list[str],
        *,
        preview_id: str,
    ) -> dict[str, Any]:
        """Execute one explicit ordered test selection on one exact clean preview."""

        selected = self._validate_selection(test_targets)
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
        subject = self.builds._subject(candidate)
        definitions = [self._definition_from_state(state, name) for name in selected]
        capabilities = self.sandbox.capabilities()
        if not capabilities.get("available"):
            raise ValidationError(
                "SANDBOX_UNAVAILABLE",
                str(capabilities.get("probe_error") or "sandbox is unavailable"),
            )

        build_order: list[str] = []
        built: dict[str, dict[str, Any]] = {}
        for definition in definitions:
            target_name = str(definition["build_target"])
            if target_name in built:
                continue
            build_order.append(target_name)
            built[target_name] = self.builds.build_exact(candidate, state, target_name)

        qualification_id = uuid.uuid4().hex
        temporary_directory = Path(
            tempfile.mkdtemp(prefix=f".{qualification_id}-", dir=self.run_root)
        )
        try:
            results: list[dict[str, Any]] = []
            for index, (name, definition) in enumerate(
                zip(selected, definitions, strict=True)
            ):
                build = built[str(definition["build_target"])]
                if build.get("status") != "succeeded":
                    results.append(
                        {
                            "test_target": name,
                            "definition_hash": definition["definition_hash"],
                            "build_target": definition["build_target"],
                            "outcome": "error",
                            "passed": None,
                            "build_id": build["build_id"],
                            "build_manifest_sha256": build["manifest_sha256"],
                            "error": {
                                "code": "MERGE_CANDIDATE_TEST_BUILD_FAILED",
                                "message": (
                                    f"candidate build {build['build_id']!r} did not "
                                    "produce an executable"
                                ),
                                "node_id": None,
                            },
                        }
                    )
                    continue
                executable_value = build.get("artifact_paths", {}).get("executable")
                if not isinstance(executable_value, str):
                    raise ArtifactIntegrityError(
                        "successful candidate build did not expose an executable"
                    )
                executable = Path(executable_value).resolve()
                executable_sha256 = self._sha256_file(executable)
                expected_executable_sha256 = build.get("artifact_sha256", {}).get(
                    build.get("artifacts", {}).get("executable")
                )
                if executable_sha256 != expected_executable_sha256:
                    raise ArtifactIntegrityError(
                        "candidate executable hash does not match build evidence"
                    )
                limits = SandboxLimits(
                    timeout_ms=int(definition["timeout_ms"]),
                    max_memory_bytes=int(definition["max_memory_bytes"]),
                    max_output_bytes=int(definition["max_output_bytes"]),
                    max_file_bytes=int(definition["max_file_bytes"]),
                )
                observed = self.sandbox.run(
                    executable,
                    list(definition["arguments"]),
                    str(definition["stdin"]).encode("utf-8"),
                    limits,
                )
                expected_stdout = str(definition["expected_stdout"]).encode("utf-8")
                expected_stderr = str(definition["expected_stderr"]).encode("utf-8")
                assertions = {
                    "completed_without_timeout": not observed.timed_out,
                    "completed_without_output_limit": not observed.output_limited,
                    "exit_code": observed.returncode
                    == int(definition["expected_exit_code"]),
                    "stdout": observed.stdout == expected_stdout,
                    "stderr": observed.stderr == expected_stderr,
                }
                passed = all(assertions.values())
                output_directory = temporary_directory / "outputs" / (
                    f"{index:03d}-{self._safe_name(name)}"
                )
                output_directory.mkdir(parents=True)
                stdout_path = output_directory / "stdout.bin"
                stderr_path = output_directory / "stderr.bin"
                stdout_path.write_bytes(observed.stdout)
                stderr_path.write_bytes(observed.stderr)
                results.append(
                    {
                        "test_target": name,
                        "definition_hash": definition["definition_hash"],
                        "build_target": definition["build_target"],
                        "outcome": "passed" if passed else "failed",
                        "passed": passed,
                        "build_id": build["build_id"],
                        "build_manifest_sha256": build["manifest_sha256"],
                        "executable_sha256": executable_sha256,
                        "limits": limits.as_dict(),
                        "expected": {
                            "exit_code": int(definition["expected_exit_code"]),
                            "stdout_bytes": len(expected_stdout),
                            "stdout_sha256": hashlib.sha256(expected_stdout).hexdigest(),
                            "stderr_bytes": len(expected_stderr),
                            "stderr_sha256": hashlib.sha256(expected_stderr).hexdigest(),
                        },
                        "observed": observed.as_dict(),
                        "assertions": assertions,
                        "artifacts": {
                            "stdout": str(stdout_path.relative_to(temporary_directory)),
                            "stderr": str(stderr_path.relative_to(temporary_directory)),
                        },
                    }
                )

            passed_count = sum(item["outcome"] == "passed" for item in results)
            failed_count = sum(item["outcome"] == "failed" for item in results)
            error_count = sum(item["outcome"] == "error" for item in results)
            status = "incomplete" if error_count else "failed" if failed_count else "passed"
            heads_unchanged = (
                self.workspace.branch_head(project, target_branch)
                == candidate["target_head_revision_id"]
                and self.workspace.branch_head(project, source_branch)
                == candidate["source_head_revision_id"]
            )
            build_bindings = [
                {
                    "build_target": target_name,
                    "build_id": built[target_name]["build_id"],
                    "build_input_hash": built[target_name]["build_input_hash"],
                    "manifest_sha256": built[target_name]["manifest_sha256"],
                    "status": built[target_name]["status"],
                }
                for target_name in build_order
            ]
            definition_bindings = [
                {
                    "test_target": name,
                    "definition_hash": definition["definition_hash"],
                    "build_target": definition["build_target"],
                }
                for name, definition in zip(selected, definitions, strict=True)
            ]
            input_document = {
                "format": MERGE_CANDIDATE_TEST_BATCH_FORMAT,
                "subject": subject,
                "test_targets": selected,
                "definitions": definition_bindings,
                "builds": build_bindings,
                "sandbox_policy_hash": capabilities["policy_hash"],
            }
            artifacts = {
                item["test_target"]: item["artifacts"]
                for item in results
                if item["outcome"] != "error"
            }
            references = set(self._artifact_references(artifacts))
            artifact_sha256 = {
                relative: self._sha256_file(temporary_directory / relative)
                for relative in sorted(references)
            }
            manifest = {
                "format": MERGE_CANDIDATE_TEST_BATCH_FORMAT,
                "qualification_id": qualification_id,
                "status": status,
                "all_passed": status == "passed",
                "subject": subject,
                "test_targets": selected,
                "definitions": definition_bindings,
                "builds": build_bindings,
                "sandbox": {
                    "backend": capabilities["backend"],
                    "version": capabilities.get("version"),
                    "policy_hash": capabilities["policy_hash"],
                    "policy": capabilities["policy"],
                    "resource_limits": capabilities.get("resource_limits", {}),
                },
                "qualification_input_hash": self._hash_json(input_document),
                "selected_test_count": len(selected),
                "passed_test_count": passed_count,
                "failed_test_count": failed_count,
                "error_test_count": error_count,
                "heads_unchanged_at_completion": heads_unchanged,
                "publication_candidate_current_at_completion": heads_unchanged,
                "results": results,
                "artifacts": artifacts,
                "artifact_sha256": artifact_sha256,
            }
            self._write_json(
                temporary_directory / "qualification-manifest.json",
                manifest,
            )
            self._verify_manifest(
                manifest,
                temporary_directory,
                expected_id=qualification_id,
            )
            final_directory = self._qualification_directory(
                qualification_id,
                require_exists=False,
            )
            with self._publication_lock(final_directory):
                if os.path.lexists(final_directory):
                    raise ArtifactIntegrityError(
                        f"merge candidate qualification {qualification_id!r} already exists"
                    )
                os.replace(temporary_directory, final_directory)
            return self.get(qualification_id)
        finally:
            if os.path.lexists(temporary_directory):
                self._remove_path(temporary_directory)

    def get(self, qualification_id: str) -> dict[str, Any]:
        """Read and verify one immutable virtual-candidate test qualification."""

        directory = self._qualification_directory(qualification_id)
        manifest_path = directory / "qualification-manifest.json"
        manifest = self._read_manifest(manifest_path)
        self._verify_manifest(manifest, directory, expected_id=qualification_id)
        result = dict(manifest)
        result["manifest_sha256"] = self._sha256_file(manifest_path)
        return result

    def output_page(
        self,
        qualification_id: str,
        test_target: str,
        stream: str,
        *,
        start_byte: int = 0,
        max_bytes: int = DEFAULT_OUTPUT_PAGE_BYTES,
    ) -> dict[str, Any]:
        """Read one bounded verified stdout or stderr page from candidate evidence."""

        if not isinstance(test_target, str) or not TEST_TARGET_NAME.fullmatch(test_target):
            raise ValidationError(
                "INVALID_TEST_TARGET_NAME",
                "test target name is invalid",
            )
        if stream not in {"stdout", "stderr"}:
            raise ValidationError(
                "INVALID_MERGE_CANDIDATE_TEST_STREAM",
                "stream must be 'stdout' or 'stderr'",
            )
        self._validate_page_number("start_byte", start_byte, 0, None)
        self._validate_page_number("max_bytes", max_bytes, 1, MAX_OUTPUT_PAGE_BYTES)
        manifest = self.get(qualification_id)
        result_items = [
            item for item in manifest["results"] if item["test_target"] == test_target
        ]
        if len(result_items) != 1:
            raise NotFoundError(
                f"test target {test_target!r} has no retained output in qualification"
            )
        result = result_items[0]
        relative = result.get("artifacts", {}).get(stream)
        if not isinstance(relative, str):
            raise NotFoundError(
                f"test target {test_target!r} has no retained {stream} output"
            )
        directory = self._qualification_directory(qualification_id)
        path = self._artifact_path(directory, relative)
        if path is None or not path.is_file():
            raise ArtifactIntegrityError("candidate test output artifact is missing")
        total_bytes = path.stat().st_size
        effective_start = min(start_byte, total_bytes)
        with path.open("rb") as handle:
            handle.seek(effective_start)
            content = handle.read(max_bytes)
        next_byte = effective_start + len(content)
        try:
            utf8_text: str | None = content.decode("utf-8")
        except UnicodeDecodeError:
            utf8_text = None
        return {
            "format": MERGE_CANDIDATE_TEST_OUTPUT_PAGE_FORMAT,
            "qualification_id": qualification_id,
            "test_target": test_target,
            "stream": stream,
            "start_byte": effective_start,
            "max_bytes": max_bytes,
            "returned_bytes": len(content),
            "total_bytes": total_bytes,
            "eof": next_byte >= total_bytes,
            "next_byte": None if next_byte >= total_bytes else next_byte,
            "content_base64": base64.b64encode(content).decode("ascii"),
            "utf8_text": utf8_text,
            "stream_sha256": manifest["artifact_sha256"][relative],
            "manifest_sha256": manifest["manifest_sha256"],
        }

    def _verify_manifest(
        self,
        manifest: dict[str, Any],
        directory: Path,
        *,
        expected_id: str,
    ) -> None:
        if manifest.get("format") != MERGE_CANDIDATE_TEST_BATCH_FORMAT:
            raise ArtifactIntegrityError("merge candidate test manifest format is invalid")
        if manifest.get("qualification_id") != expected_id:
            raise ArtifactIntegrityError("merge candidate qualification identity is invalid")
        status = manifest.get("status")
        if status not in {"passed", "failed", "incomplete"}:
            raise ArtifactIntegrityError("merge candidate qualification status is invalid")
        subject = manifest.get("subject")
        if not isinstance(subject, dict):
            raise ArtifactIntegrityError("merge candidate qualification subject is invalid")
        state = self.builds._reconstruct_subject_state(subject)
        selected = manifest.get("test_targets")
        definitions = manifest.get("definitions")
        results = manifest.get("results")
        if not isinstance(selected, list) or not selected:
            raise ArtifactIntegrityError("merge candidate test selection is invalid")
        if len(selected) > MAX_MERGE_CANDIDATE_TESTS or len(set(selected)) != len(selected):
            raise ArtifactIntegrityError("merge candidate test selection bounds are invalid")
        if not isinstance(definitions, list) or len(definitions) != len(selected):
            raise ArtifactIntegrityError("merge candidate definition count is invalid")
        if not isinstance(results, list) or len(results) != len(selected):
            raise ArtifactIntegrityError("merge candidate result count is invalid")
        if [item.get("test_target") for item in definitions] != selected:
            raise ArtifactIntegrityError("merge candidate definition order is invalid")
        if [item.get("test_target") for item in results] != selected:
            raise ArtifactIntegrityError("merge candidate result order is invalid")
        expected_definitions = [
            self._definition_from_state(state, name) for name in selected
        ]
        expected_bindings = [
            {
                "test_target": name,
                "definition_hash": definition["definition_hash"],
                "build_target": definition["build_target"],
            }
            for name, definition in zip(selected, expected_definitions, strict=True)
        ]
        if definitions != expected_bindings:
            raise ArtifactIntegrityError("merge candidate definition evidence is invalid")
        build_records = manifest.get("builds")
        if not isinstance(build_records, list):
            raise ArtifactIntegrityError("merge candidate build bindings are invalid")
        build_by_target: dict[str, dict[str, Any]] = {}
        for record in build_records:
            target_name = record.get("build_target")
            if not isinstance(target_name, str) or target_name in build_by_target:
                raise ArtifactIntegrityError("merge candidate build target order is invalid")
            build = self.builds.get(record.get("build_id"))
            if build["subject"] != subject:
                raise ArtifactIntegrityError("candidate build subject does not match qualification")
            if build["build_target"]["name"] != target_name:
                raise ArtifactIntegrityError("candidate build target identity is invalid")
            if build["build_input_hash"] != record.get("build_input_hash"):
                raise ArtifactIntegrityError("candidate build input hash is invalid")
            if build["manifest_sha256"] != record.get("manifest_sha256"):
                raise ArtifactIntegrityError("candidate build manifest hash is invalid")
            if build["status"] != record.get("status"):
                raise ArtifactIntegrityError("candidate build status is invalid")
            build_by_target[target_name] = build
        required_targets = []
        for definition in expected_definitions:
            target_name = str(definition["build_target"])
            if target_name not in required_targets:
                required_targets.append(target_name)
        if list(build_by_target) != required_targets:
            raise ArtifactIntegrityError("candidate build binding order is invalid")
        outcomes = [item.get("outcome") for item in results]
        if any(value not in {"passed", "failed", "error"} for value in outcomes):
            raise ArtifactIntegrityError("merge candidate result outcome is invalid")
        counts = {
            "passed": outcomes.count("passed"),
            "failed": outcomes.count("failed"),
            "error": outcomes.count("error"),
        }
        for outcome, field in (
            ("passed", "passed_test_count"),
            ("failed", "failed_test_count"),
            ("error", "error_test_count"),
        ):
            if manifest.get(field) != counts[outcome]:
                raise ArtifactIntegrityError(
                    f"merge candidate {outcome} count is invalid"
                )
        if manifest.get("selected_test_count") != len(selected):
            raise ArtifactIntegrityError("merge candidate selected count is invalid")
        expected_status = (
            "incomplete" if counts["error"] else "failed" if counts["failed"] else "passed"
        )
        if status != expected_status or manifest.get("all_passed") is not (
            expected_status == "passed"
        ):
            raise ArtifactIntegrityError("merge candidate aggregate status is invalid")
        for definition, result in zip(expected_definitions, results, strict=True):
            if result.get("definition_hash") != definition["definition_hash"]:
                raise ArtifactIntegrityError("merge candidate result definition hash is invalid")
            if result.get("build_target") != definition["build_target"]:
                raise ArtifactIntegrityError("merge candidate result build target is invalid")
            build = build_by_target[str(definition["build_target"])]
            if result.get("build_id") != build["build_id"]:
                raise ArtifactIntegrityError("merge candidate result build ID is invalid")
            if result.get("build_manifest_sha256") != build["manifest_sha256"]:
                raise ArtifactIntegrityError("merge candidate result build hash is invalid")
            if result["outcome"] == "error":
                if build["status"] == "succeeded" or result.get("passed") is not None:
                    raise ArtifactIntegrityError("merge candidate error result is invalid")
                continue
            if build["status"] != "succeeded":
                raise ArtifactIntegrityError("candidate result used a failed build")
            if bool(result.get("passed")) != (result["outcome"] == "passed"):
                raise ArtifactIntegrityError("merge candidate pass status is invalid")
            assertions = result.get("assertions")
            if not isinstance(assertions, dict) or bool(result["passed"]) != all(
                assertions.values()
            ):
                raise ArtifactIntegrityError("merge candidate assertions are invalid")
        input_document = {
            "format": MERGE_CANDIDATE_TEST_BATCH_FORMAT,
            "subject": subject,
            "test_targets": selected,
            "definitions": definitions,
            "builds": build_records,
            "sandbox_policy_hash": manifest.get("sandbox", {}).get("policy_hash"),
        }
        if manifest.get("qualification_input_hash") != self._hash_json(input_document):
            raise ArtifactIntegrityError("merge candidate qualification input hash is invalid")
        try:
            self._verify_artifacts(manifest, directory)
        except ValidationError as exc:
            raise ArtifactIntegrityError(str(exc)) from exc
        for result in results:
            if result["outcome"] == "error":
                continue
            for stream in ("stdout", "stderr"):
                relative = result.get("artifacts", {}).get(stream)
                actual_hash = manifest.get("artifact_sha256", {}).get(relative)
                observed_hash = result.get("observed", {}).get(f"{stream}_sha256")
                if actual_hash != observed_hash:
                    raise ArtifactIntegrityError(
                        f"merge candidate {stream} observation hash is invalid"
                    )

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

    def _definition_from_state(
        self,
        state: dict[str, Any],
        name: str,
    ) -> dict[str, Any]:
        test_name = self.tests._validate_name(name)
        storage_document = self.tests._storage_document(test_name)
        try:
            root = state[storage_document]
        except KeyError as exc:
            raise NotFoundError(f"test target {test_name!r} not found") from exc
        config = self.tests._parse_tree(root, name=test_name)
        self.tests._require_build_target(state, str(config["build_target"]))
        return {
            **config,
            "definition_hash": self.workspace.db.hash_value(root),
        }

    @staticmethod
    def _validate_selection(test_targets: Any) -> list[str]:
        if not isinstance(test_targets, list):
            raise ValidationError(
                "INVALID_MERGE_CANDIDATE_TEST_SELECTION",
                "test_targets must be a list",
            )
        if not test_targets or len(test_targets) > MAX_MERGE_CANDIDATE_TESTS:
            raise ValidationError(
                "INVALID_MERGE_CANDIDATE_TEST_SELECTION",
                f"test_targets must contain between 1 and {MAX_MERGE_CANDIDATE_TESTS} names",
            )
        selected: list[str] = []
        seen: set[str] = set()
        for name in test_targets:
            if not isinstance(name, str) or not TEST_TARGET_NAME.fullmatch(name):
                raise ValidationError(
                    "INVALID_MERGE_CANDIDATE_TEST_SELECTION",
                    "every test target must be a valid test-target name",
                )
            if name in seen:
                raise ValidationError(
                    "INVALID_MERGE_CANDIDATE_TEST_SELECTION",
                    f"duplicate test target {name!r}",
                )
            seen.add(name)
            selected.append(name)
        return selected

    def _qualification_directory(
        self,
        qualification_id: str,
        *,
        require_exists: bool = True,
    ) -> Path:
        if not isinstance(qualification_id, str) or not MERGE_CANDIDATE_TEST_BATCH_ID.fullmatch(
            qualification_id
        ):
            raise ValidationError(
                "INVALID_MERGE_CANDIDATE_QUALIFICATION_ID",
                "qualification_id must be 32 lowercase hexadecimal characters",
            )
        directory = (self.run_root / qualification_id).resolve()
        if directory.parent != self.run_root:
            raise ValidationError(
                "INVALID_MERGE_CANDIDATE_QUALIFICATION_ID",
                "qualification_id escapes run root",
            )
        if require_exists and not directory.is_dir():
            raise NotFoundError(
                f"merge candidate qualification {qualification_id!r} not found"
            )
        return directory

    @staticmethod
    def _read_manifest(path: Path) -> dict[str, Any]:
        try:
            value = read_bounded_regular_json(
                path,
                max_bytes=MAX_MERGE_CANDIDATE_TEST_MANIFEST_BYTES,
            )
        except RetainedArtifactReadError as exc:
            raise ArtifactIntegrityError(
                f"cannot read merge candidate qualification manifest: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise ArtifactIntegrityError(
                "merge candidate qualification manifest root must be an object"
            )
        return value

    @staticmethod
    def _validate_page_number(
        name: str,
        value: Any,
        minimum: int,
        maximum: int | None,
    ) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationError(
                "INVALID_MERGE_CANDIDATE_OUTPUT_PAGE",
                f"{name} must be an integer",
            )
        if value < minimum or (maximum is not None and value > maximum):
            upper = "unbounded" if maximum is None else str(maximum)
            raise ValidationError(
                "INVALID_MERGE_CANDIDATE_OUTPUT_PAGE",
                f"{name} must be between {minimum} and {upper}",
            )

    @staticmethod
    def _safe_name(value: str) -> str:
        return "".join(
            character if character.isalnum() or character in {".", "_", "-"} else "_"
            for character in value
        )

    @staticmethod
    def _hash_json(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
