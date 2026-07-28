"""Revision-pinned sandboxed behavioral test execution and immutable evidence."""

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

from .compiler_artifacts import CompilerArtifactMixin
from .errors import ArtifactIntegrityError, NotFoundError, ValidationError
from .retained_artifact_io import (
    RetainedArtifactReadError,
    read_bounded_regular_json,
)
from .sandbox import BubblewrapSandbox, SandboxBackend, SandboxLimits
from .test_target_views import VerifiedTestTargetRegistry

TEST_RUN_MANIFEST_FORMAT = "weave-test-run-manifest-v1"
TEST_RUN_OUTPUT_PAGE_FORMAT = "weave-test-run-output-page-v1"
TEST_RUN_ID = re.compile(r"^[0-9a-f]{32}$")
MAX_TEST_RUN_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_TEST_RUN_OUTPUT_PAGE_BYTES = 65_536
DEFAULT_TEST_RUN_OUTPUT_PAGE_BYTES = 16_384


class TestRunService(CompilerArtifactMixin):
    """Build, sandbox, compare, retain, and verify exact behavioral test runs."""

    def __init__(
        self,
        workspace: Any,
        build_targets: Any,
        tests: VerifiedTestTargetRegistry,
        compiler: Any,
        sandbox: SandboxBackend | None = None,
        *,
        run_root: str | Path | None = None,
    ) -> None:
        self.workspace = workspace
        self.build_targets = build_targets
        self.tests = tests
        self.compiler = compiler
        self.sandbox = sandbox or BubblewrapSandbox()
        configured_root = run_root or os.environ.get("WEAVE_TEST_RUN_ROOT")
        if configured_root is None:
            configured_root = workspace.db.path.parent / ".weave-test-runs"
        self.run_root = Path(configured_root).resolve()
        self.run_root.mkdir(parents=True, exist_ok=True)

    def capabilities(self) -> dict[str, Any]:
        """Return the probed sandbox backend and exact enforced policy."""

        return self.sandbox.capabilities()

    def run(
        self,
        project: str,
        test_target: str,
        *,
        branch: str = "main",
        revision_id: str | None = None,
    ) -> dict[str, Any]:
        revision = revision_id or self.workspace.branch_head(project, branch)
        definition = self.tests.get(
            project,
            test_target,
            branch=branch,
            revision_id=revision,
        )
        target = self.build_targets.get(
            project,
            str(definition["build_target"]),
            branch=branch,
            revision_id=revision,
        )
        build = self.compiler.build(
            project,
            str(target["document"]),
            additional_documents=list(target["additional_documents"]),
            branch=branch,
            revision_id=revision,
            target=target["compiler_target"],
        )
        if build.get("status") != "succeeded":
            raise ValidationError(
                "TEST_BUILD_FAILED",
                f"build {build.get('build_id')!r} did not produce an executable",
            )
        executable_value = build.get("artifact_paths", {}).get("executable")
        if not isinstance(executable_value, str):
            raise ValidationError(
                "TEST_BUILD_FAILED",
                "successful build did not publish an executable artifact",
            )
        executable = Path(executable_value).resolve()
        executable_hash = self._sha256_file(executable)
        expected_executable_hash = self._expected_executable_hash(build)
        if executable_hash != expected_executable_hash:
            raise ArtifactIntegrityError(
                "build executable hash does not match retained build evidence"
            )

        capabilities = self.sandbox.capabilities()
        if not capabilities.get("available"):
            raise ValidationError(
                "SANDBOX_UNAVAILABLE",
                str(capabilities.get("probe_error") or "sandbox is unavailable"),
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
            "exit_code": observed.returncode == int(definition["expected_exit_code"]),
            "stdout": observed.stdout == expected_stdout,
            "stderr": observed.stderr == expected_stderr,
        }
        passed = all(assertions.values())
        run_id = uuid.uuid4().hex
        sandbox_policy = {
            "backend": capabilities["backend"],
            "version": capabilities.get("version"),
            "policy_hash": capabilities["policy_hash"],
            "policy": capabilities["policy"],
            "limits": limits.as_dict(),
        }
        input_document = {
            "project": project,
            "branch": branch,
            "revision_id": revision,
            "test_target": test_target,
            "definition_hash": definition["definition_hash"],
            "build_id": build["build_id"],
            "executable_sha256": executable_hash,
            "sandbox_policy_hash": capabilities["policy_hash"],
            "limits": limits.as_dict(),
        }
        run_input_hash = self._hash_json(input_document)
        expected = {
            "exit_code": int(definition["expected_exit_code"]),
            "stdout_bytes": len(expected_stdout),
            "stdout_sha256": hashlib.sha256(expected_stdout).hexdigest(),
            "stderr_bytes": len(expected_stderr),
            "stderr_sha256": hashlib.sha256(expected_stderr).hexdigest(),
        }
        observed_document = observed.as_dict()
        manifest = {
            "format": TEST_RUN_MANIFEST_FORMAT,
            "run_id": run_id,
            "status": "passed" if passed else "failed",
            "passed": passed,
            "project": project,
            "branch": branch,
            "revision_id": revision,
            "test_target": test_target,
            "definition_hash": definition["definition_hash"],
            "build_id": build["build_id"],
            "build_revision_hash": build["revision_hash"],
            "compiler_sha256": build["compiler_sha256"],
            "executable_sha256": executable_hash,
            "sandbox": sandbox_policy,
            "run_input_hash": run_input_hash,
            "expected": expected,
            "observed": observed_document,
            "assertions": assertions,
            "artifacts": {
                "stdout": "stdout.bin",
                "stderr": "stderr.bin",
            },
            "artifact_sha256": {
                "stdout": hashlib.sha256(observed.stdout).hexdigest(),
                "stderr": hashlib.sha256(observed.stderr).hexdigest(),
            },
        }
        self._publish_run(run_id, manifest, observed.stdout, observed.stderr)
        return self.get(run_id)

    def get(self, run_id: str) -> dict[str, Any]:
        """Read and verify one immutable run manifest and its retained output bytes."""

        run_directory = self._run_directory(run_id)
        manifest_path = run_directory / "run-manifest.json"
        manifest = self._read_json(manifest_path)
        if manifest.get("format") != TEST_RUN_MANIFEST_FORMAT:
            raise ArtifactIntegrityError("test run manifest format is invalid")
        if manifest.get("run_id") != run_id:
            raise ArtifactIntegrityError("test run manifest identity is invalid")
        artifact_paths: dict[str, str] = {"manifest": str(manifest_path.resolve())}
        for name in ("stdout", "stderr"):
            relative = manifest.get("artifacts", {}).get(name)
            if relative != f"{name}.bin":
                raise ArtifactIntegrityError(f"test run {name} artifact path is invalid")
            path = (run_directory / relative).resolve()
            if path.parent != run_directory.resolve() or not path.is_file():
                raise ArtifactIntegrityError(f"test run {name} artifact is missing")
            actual_hash = self._sha256_file(path)
            expected_hash = manifest.get("artifact_sha256", {}).get(name)
            if actual_hash != expected_hash:
                raise ArtifactIntegrityError(f"test run {name} artifact hash is invalid")
            observed_hash = manifest.get("observed", {}).get(f"{name}_sha256")
            if actual_hash != observed_hash:
                raise ArtifactIntegrityError(
                    f"test run {name} observation hash is invalid"
                )
            artifact_paths[name] = str(path)
        result = dict(manifest)
        result["artifact_paths"] = artifact_paths
        result["manifest_sha256"] = self._sha256_file(manifest_path)
        return result

    def output_page(
        self,
        run_id: str,
        stream: str,
        *,
        start_byte: int = 0,
        max_bytes: int = DEFAULT_TEST_RUN_OUTPUT_PAGE_BYTES,
    ) -> dict[str, Any]:
        """Read a verified bounded stdout or stderr byte page."""

        if stream not in {"stdout", "stderr"}:
            raise ValidationError(
                "INVALID_TEST_RUN_STREAM",
                "stream must be 'stdout' or 'stderr'",
            )
        self._validate_page_number("start_byte", start_byte, minimum=0, maximum=None)
        self._validate_page_number(
            "max_bytes",
            max_bytes,
            minimum=1,
            maximum=MAX_TEST_RUN_OUTPUT_PAGE_BYTES,
        )
        run = self.get(run_id)
        path = Path(run["artifact_paths"][stream])
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
            "format": TEST_RUN_OUTPUT_PAGE_FORMAT,
            "run_id": run_id,
            "stream": stream,
            "start_byte": effective_start,
            "max_bytes": max_bytes,
            "returned_bytes": len(content),
            "total_bytes": total_bytes,
            "eof": next_byte >= total_bytes,
            "next_byte": None if next_byte >= total_bytes else next_byte,
            "content_base64": base64.b64encode(content).decode("ascii"),
            "utf8_text": utf8_text,
            "stream_sha256": run["artifact_sha256"][stream],
            "manifest_sha256": run["manifest_sha256"],
        }

    def _publish_run(
        self,
        run_id: str,
        manifest: dict[str, Any],
        stdout: bytes,
        stderr: bytes,
    ) -> None:
        final_directory = self._run_directory(run_id, require_exists=False)
        with tempfile.TemporaryDirectory(
            prefix=f".{run_id}-",
            dir=self.run_root,
        ) as temporary:
            temporary_directory = Path(temporary)
            (temporary_directory / "stdout.bin").write_bytes(stdout)
            (temporary_directory / "stderr.bin").write_bytes(stderr)
            self._write_json(temporary_directory / "run-manifest.json", manifest)
            self._verify_staged_run(temporary_directory, run_id)
            with self._publication_lock(final_directory):
                if os.path.lexists(final_directory):
                    raise ArtifactIntegrityError(f"test run {run_id!r} already exists")
                os.replace(temporary_directory, final_directory)

    def _verify_staged_run(self, directory: Path, run_id: str) -> None:
        manifest = self._read_json(directory / "run-manifest.json")
        if manifest.get("format") != TEST_RUN_MANIFEST_FORMAT:
            raise ArtifactIntegrityError("staged test run manifest format is invalid")
        if manifest.get("run_id") != run_id:
            raise ArtifactIntegrityError("staged test run identity is invalid")
        for name in ("stdout", "stderr"):
            path = directory / f"{name}.bin"
            if not path.is_file():
                raise ArtifactIntegrityError(f"staged test run {name} artifact is missing")
            expected = manifest.get("artifact_sha256", {}).get(name)
            if self._sha256_file(path) != expected:
                raise ArtifactIntegrityError(
                    f"staged test run {name} artifact hash is invalid"
                )

    def _run_directory(self, run_id: str, *, require_exists: bool = True) -> Path:
        if not isinstance(run_id, str) or not TEST_RUN_ID.fullmatch(run_id):
            raise ValidationError(
                "INVALID_TEST_RUN_ID",
                "run_id must be 32 lowercase hexadecimal characters",
            )
        directory = (self.run_root / run_id).resolve()
        if directory.parent != self.run_root:
            raise ValidationError("INVALID_TEST_RUN_ID", "run_id escapes run root")
        if require_exists and not directory.is_dir():
            raise NotFoundError(f"test run {run_id!r} not found")
        return directory

    @staticmethod
    def _expected_executable_hash(build: dict[str, Any]) -> Any:
        artifact_hashes = build.get("artifact_sha256", {})
        relative = build.get("artifacts", {}).get("executable")
        if isinstance(relative, str):
            return artifact_hashes.get(relative)
        return artifact_hashes.get("executable")

    @staticmethod
    def _hash_json(value: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            value = read_bounded_regular_json(
                path,
                max_bytes=MAX_TEST_RUN_MANIFEST_BYTES,
            )
        except RetainedArtifactReadError as exc:
            raise ArtifactIntegrityError(f"cannot read test run manifest: {exc}") from exc
        if not isinstance(value, dict):
            raise ArtifactIntegrityError("test run manifest root must be an object")
        return value

    @staticmethod
    def _validate_page_number(
        name: str,
        value: Any,
        *,
        minimum: int,
        maximum: int | None,
    ) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationError(
                "INVALID_TEST_RUN_OUTPUT_PAGE",
                f"{name} must be an integer",
            )
        if value < minimum or (maximum is not None and value > maximum):
            suffix = f" and {maximum}" if maximum is not None else ""
            raise ValidationError(
                "INVALID_TEST_RUN_OUTPUT_PAGE",
                f"{name} must be between {minimum}{suffix}",
            )
