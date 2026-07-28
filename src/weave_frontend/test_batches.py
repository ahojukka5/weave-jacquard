"""Bounded explicit behavioral-test batches with immutable aggregate evidence."""

from __future__ import annotations

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
from .test_targets import TEST_TARGET_NAME

TEST_BATCH_MANIFEST_FORMAT = "weave-test-batch-manifest-v1"
TEST_BATCH_ID = re.compile(r"^[0-9a-f]{32}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_TEST_BATCH_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_TEST_BATCH_TARGETS = 64


class TestBatchService(CompilerArtifactMixin):
    """Run one explicit ordered test set at one exact immutable revision."""

    def __init__(
        self,
        workspace: Any,
        tests: Any,
        runs: Any,
        *,
        batch_root: str | Path | None = None,
    ) -> None:
        self.workspace = workspace
        self.tests = tests
        self.runs = runs
        configured_root = batch_root or os.environ.get("WEAVE_TEST_BATCH_ROOT")
        if configured_root is None:
            configured_root = Path(runs.run_root) / "batches"
        self.batch_root = Path(configured_root).resolve()
        self.batch_root.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        project: str,
        test_targets: list[str],
        *,
        branch: str = "main",
        revision_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute a validated caller-ordered test set and retain one batch manifest."""

        selected = self._validate_selection(test_targets)
        revision = revision_id or self.workspace.branch_head(project, branch)
        definitions = [
            self.tests.get(
                project,
                name,
                branch=branch,
                revision_id=revision,
            )
            for name in selected
        ]
        capabilities = self.runs.capabilities()
        if not capabilities.get("available"):
            raise ValidationError(
                "SANDBOX_UNAVAILABLE",
                str(capabilities.get("probe_error") or "sandbox is unavailable"),
            )

        results: list[dict[str, Any]] = []
        for name, definition in zip(selected, definitions, strict=True):
            try:
                run = self.runs.run(
                    project,
                    name,
                    branch=branch,
                    revision_id=revision,
                )
            except ValidationError as exc:
                if exc.code == "SANDBOX_UNAVAILABLE":
                    raise
                results.append(
                    {
                        "test_target": name,
                        "definition_hash": definition["definition_hash"],
                        "outcome": "error",
                        "passed": None,
                        "error": exc.as_dict(),
                    }
                )
                continue
            results.append(
                {
                    "test_target": name,
                    "definition_hash": definition["definition_hash"],
                    "outcome": "passed" if run["passed"] else "failed",
                    "passed": bool(run["passed"]),
                    "run_id": run["run_id"],
                    "run_manifest_sha256": run["manifest_sha256"],
                }
            )

        passed_count = sum(item["outcome"] == "passed" for item in results)
        failed_count = sum(item["outcome"] == "failed" for item in results)
        error_count = sum(item["outcome"] == "error" for item in results)
        if error_count:
            status = "incomplete"
        elif failed_count:
            status = "failed"
        else:
            status = "passed"
        batch_id = uuid.uuid4().hex
        definition_bindings = [
            {
                "test_target": name,
                "definition_hash": definition["definition_hash"],
            }
            for name, definition in zip(selected, definitions, strict=True)
        ]
        input_document = {
            "project": project,
            "branch": branch,
            "revision_id": revision,
            "test_targets": selected,
            "definitions": definition_bindings,
            "sandbox_policy_hash": capabilities["policy_hash"],
        }
        manifest = {
            "format": TEST_BATCH_MANIFEST_FORMAT,
            "batch_id": batch_id,
            "status": status,
            "all_passed": status == "passed",
            "project": project,
            "branch": branch,
            "revision_id": revision,
            "test_targets": selected,
            "definitions": definition_bindings,
            "sandbox": {
                "backend": capabilities["backend"],
                "version": capabilities.get("version"),
                "policy_hash": capabilities["policy_hash"],
                "policy": capabilities["policy"],
                "resource_limits": capabilities.get("resource_limits", {}),
            },
            "batch_input_hash": self._hash_json(input_document),
            "selected_test_count": len(selected),
            "passed_test_count": passed_count,
            "failed_test_count": failed_count,
            "error_test_count": error_count,
            "results": results,
        }
        self._publish(batch_id, manifest)
        return self.get(batch_id)

    def get(self, batch_id: str) -> dict[str, Any]:
        """Read one batch manifest and verify all referenced run evidence."""

        directory = self._batch_directory(batch_id)
        manifest_path = directory / "batch-manifest.json"
        manifest = self._read_json(manifest_path)
        self._verify_manifest(manifest, batch_id)
        sandbox_policy_hash = manifest["sandbox"]["policy_hash"]
        for item in manifest["results"]:
            if item["outcome"] == "error":
                continue
            run = self.runs.get(item["run_id"])
            self._require_equal(
                run.get("manifest_sha256"),
                item["run_manifest_sha256"],
                item["test_target"],
                "run manifest hash",
            )
            self._require_equal(
                run.get("project"),
                manifest["project"],
                item["test_target"],
                "project",
            )
            self._require_equal(
                run.get("branch"),
                manifest["branch"],
                item["test_target"],
                "branch",
            )
            self._require_equal(
                run.get("revision_id"),
                manifest["revision_id"],
                item["test_target"],
                "revision",
            )
            self._require_equal(
                run.get("test_target"),
                item["test_target"],
                item["test_target"],
                "test target",
            )
            self._require_equal(
                run.get("definition_hash"),
                item["definition_hash"],
                item["test_target"],
                "definition hash",
            )
            run_sandbox = run.get("sandbox")
            run_policy_hash = (
                run_sandbox.get("policy_hash") if isinstance(run_sandbox, dict) else None
            )
            self._require_equal(
                run_policy_hash,
                sandbox_policy_hash,
                item["test_target"],
                "sandbox policy hash",
            )
            if run.get("passed") is not item["passed"]:
                raise ArtifactIntegrityError(
                    f"test batch pass status is invalid: {item['test_target']!r}"
                )
        result = dict(manifest)
        result["manifest_sha256"] = self._sha256_file(manifest_path)
        return result

    @staticmethod
    def _validate_selection(test_targets: Any) -> list[str]:
        if not isinstance(test_targets, list):
            raise ValidationError(
                "INVALID_TEST_BATCH_SELECTION",
                "test_targets must be a list",
            )
        if not test_targets or len(test_targets) > MAX_TEST_BATCH_TARGETS:
            raise ValidationError(
                "INVALID_TEST_BATCH_SELECTION",
                f"test_targets must contain between 1 and {MAX_TEST_BATCH_TARGETS} names",
            )
        selected: list[str] = []
        seen: set[str] = set()
        for name in test_targets:
            if not isinstance(name, str) or not TEST_TARGET_NAME.fullmatch(name):
                raise ValidationError(
                    "INVALID_TEST_BATCH_SELECTION",
                    "every test target must be a valid test-target name",
                )
            if name in seen:
                raise ValidationError(
                    "INVALID_TEST_BATCH_SELECTION",
                    f"duplicate test target {name!r}",
                )
            seen.add(name)
            selected.append(name)
        return selected

    def _publish(self, batch_id: str, manifest: dict[str, Any]) -> None:
        final_directory = self._batch_directory(batch_id, require_exists=False)
        with tempfile.TemporaryDirectory(
            prefix=f".{batch_id}-",
            dir=self.batch_root,
        ) as temporary:
            temporary_directory = Path(temporary)
            manifest_path = temporary_directory / "batch-manifest.json"
            self._write_json(manifest_path, manifest)
            self._verify_manifest(self._read_json(manifest_path), batch_id)
            with self._publication_lock(final_directory):
                if os.path.lexists(final_directory):
                    raise ArtifactIntegrityError(f"test batch {batch_id!r} already exists")
                os.replace(temporary_directory, final_directory)

    def _batch_directory(self, batch_id: str, *, require_exists: bool = True) -> Path:
        if not isinstance(batch_id, str) or not TEST_BATCH_ID.fullmatch(batch_id):
            raise ValidationError(
                "INVALID_TEST_BATCH_ID",
                "batch_id must be 32 lowercase hexadecimal characters",
            )
        directory = (self.batch_root / batch_id).resolve()
        if directory.parent != self.batch_root:
            raise ValidationError("INVALID_TEST_BATCH_ID", "batch_id escapes batch root")
        if require_exists and not directory.is_dir():
            raise NotFoundError(f"test batch {batch_id!r} not found")
        return directory

    @classmethod
    def _verify_manifest(cls, manifest: dict[str, Any], batch_id: str) -> None:
        if manifest.get("format") != TEST_BATCH_MANIFEST_FORMAT:
            raise ArtifactIntegrityError("test batch manifest format is invalid")
        if manifest.get("batch_id") != batch_id:
            raise ArtifactIntegrityError("test batch manifest identity is invalid")
        status = manifest.get("status")
        if status not in {"passed", "failed", "incomplete"}:
            raise ArtifactIntegrityError("test batch status is invalid")
        for field in ("project", "branch", "revision_id"):
            if not isinstance(manifest.get(field), str) or not manifest[field]:
                raise ArtifactIntegrityError(f"test batch {field} is invalid")

        targets = manifest.get("test_targets")
        definitions = manifest.get("definitions")
        results = manifest.get("results")
        if not cls._valid_manifest_selection(targets):
            raise ArtifactIntegrityError("test batch selection is invalid")
        if manifest.get("selected_test_count") != len(targets):
            raise ArtifactIntegrityError("test batch selected count is invalid")
        if not isinstance(definitions, list) or len(definitions) != len(targets):
            raise ArtifactIntegrityError("test batch definition count is invalid")
        if not isinstance(results, list) or len(results) != len(targets):
            raise ArtifactIntegrityError("test batch result count is invalid")
        if any(not isinstance(item, dict) for item in definitions):
            raise ArtifactIntegrityError("test batch definition entry is invalid")
        if any(not isinstance(item, dict) for item in results):
            raise ArtifactIntegrityError("test batch result entry is invalid")
        if [item.get("test_target") for item in definitions] != targets:
            raise ArtifactIntegrityError("test batch definition order is invalid")
        if [item.get("test_target") for item in results] != targets:
            raise ArtifactIntegrityError("test batch result order is invalid")

        definition_hashes: list[str] = []
        for item in definitions:
            definition_hash = item.get("definition_hash")
            if not cls._valid_sha256(definition_hash):
                raise ArtifactIntegrityError("test batch definition hash is invalid")
            definition_hashes.append(definition_hash)

        run_ids: set[str] = set()
        outcomes: list[str] = []
        for index, item in enumerate(results):
            outcome = item.get("outcome")
            if outcome not in {"passed", "failed", "error"}:
                raise ArtifactIntegrityError("test batch result outcome is invalid")
            outcomes.append(outcome)
            if item.get("definition_hash") != definition_hashes[index]:
                raise ArtifactIntegrityError("test batch result definition hash is invalid")
            if outcome == "error":
                if item.get("passed") is not None:
                    raise ArtifactIntegrityError("test batch error pass status is invalid")
                error = item.get("error")
                if not isinstance(error, dict):
                    raise ArtifactIntegrityError("test batch error evidence is invalid")
                if not isinstance(error.get("code"), str) or not error["code"]:
                    raise ArtifactIntegrityError("test batch error code is invalid")
                if not isinstance(error.get("message"), str):
                    raise ArtifactIntegrityError("test batch error message is invalid")
                if "run_id" in item or "run_manifest_sha256" in item:
                    raise ArtifactIntegrityError("test batch error run identity is invalid")
                continue

            expected_passed = outcome == "passed"
            if item.get("passed") is not expected_passed:
                raise ArtifactIntegrityError("test batch result pass status is invalid")
            run_id = item.get("run_id")
            if not isinstance(run_id, str) or not TEST_BATCH_ID.fullmatch(run_id):
                raise ArtifactIntegrityError("test batch run identity is invalid")
            if run_id in run_ids:
                raise ArtifactIntegrityError("test batch run identities are not unique")
            run_ids.add(run_id)
            if not cls._valid_sha256(item.get("run_manifest_sha256")):
                raise ArtifactIntegrityError("test batch run manifest hash is invalid")

        sandbox = manifest.get("sandbox")
        if not isinstance(sandbox, dict):
            raise ArtifactIntegrityError("test batch sandbox evidence is invalid")
        if not isinstance(sandbox.get("backend"), str) or not sandbox["backend"]:
            raise ArtifactIntegrityError("test batch sandbox backend is invalid")
        if not cls._valid_sha256(sandbox.get("policy_hash")):
            raise ArtifactIntegrityError("test batch sandbox policy hash is invalid")
        if not isinstance(sandbox.get("policy"), dict):
            raise ArtifactIntegrityError("test batch sandbox policy is invalid")
        if not isinstance(sandbox.get("resource_limits"), dict):
            raise ArtifactIntegrityError("test batch sandbox resource limits are invalid")

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
                raise ArtifactIntegrityError(f"test batch {outcome} count is invalid")
        expected_status = (
            "incomplete"
            if counts["error"]
            else "failed"
            if counts["failed"]
            else "passed"
        )
        if status != expected_status or manifest.get("all_passed") is not (
            expected_status == "passed"
        ):
            raise ArtifactIntegrityError("test batch aggregate status is invalid")

        input_document = {
            "project": manifest["project"],
            "branch": manifest["branch"],
            "revision_id": manifest["revision_id"],
            "test_targets": targets,
            "definitions": definitions,
            "sandbox_policy_hash": sandbox["policy_hash"],
        }
        expected_input_hash = cls._hash_json(input_document)
        if manifest.get("batch_input_hash") != expected_input_hash:
            raise ArtifactIntegrityError("test batch input hash is invalid")

    @staticmethod
    def _valid_manifest_selection(value: Any) -> bool:
        return (
            isinstance(value, list)
            and 1 <= len(value) <= MAX_TEST_BATCH_TARGETS
            and all(
                isinstance(name, str) and TEST_TARGET_NAME.fullmatch(name)
                for name in value
            )
            and len(set(value)) == len(value)
        )

    @staticmethod
    def _valid_sha256(value: Any) -> bool:
        return isinstance(value, str) and _SHA256.fullmatch(value) is not None

    @staticmethod
    def _require_equal(
        actual: Any,
        expected: Any,
        test_target: str,
        field: str,
    ) -> None:
        if actual != expected:
            raise ArtifactIntegrityError(
                f"test batch {field} is invalid: {test_target!r}"
            )

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
                max_bytes=MAX_TEST_BATCH_MANIFEST_BYTES,
            )
        except RetainedArtifactReadError as exc:
            raise ArtifactIntegrityError(f"cannot read test batch manifest: {exc}") from exc
        if not isinstance(value, dict):
            raise ArtifactIntegrityError("test batch manifest root must be an object")
        return value
