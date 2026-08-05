"""Immutable provenance linking virtual-candidate tests to committed merge states."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .compiler import CompilerArtifactMixin
from .errors import ArtifactIntegrityError, NotFoundError, ValidationError
from .retained_artifact_io import (
    RetainedArtifactReadError,
    read_bounded_regular_json,
)

TESTED_MERGE_ATTESTATION_FORMAT = "weave-tested-merge-attestation-v1"
TESTED_MERGE_ATTESTATION_KEY_FORMAT = "weave-tested-merge-attestation-key-v1"
TESTED_MERGE_ATTESTATION_ID = re.compile(r"^[0-9a-f]{32}$")
MAX_TESTED_MERGE_ATTESTATION_BYTES = 4 * 1024 * 1024


class TestedMergeAttestationService(CompilerArtifactMixin):
    """Prove that one committed merge equals one previously tested candidate state."""

    def __init__(
        self,
        workspace: Any,
        qualifications: Any,
        *,
        attestation_root: str | Path | None = None,
    ) -> None:
        self.workspace = workspace
        self.qualifications = qualifications
        configured = attestation_root or os.environ.get("WEAVE_MERGE_ATTESTATION_ROOT")
        if configured is None:
            configured = workspace.db.path.parent / ".weave-merge-attestations"
        self.attestation_root = Path(configured).resolve()
        self.attestation_root.mkdir(parents=True, exist_ok=True)

    def attest(
        self,
        qualification_id: str,
        merged_revision_id: str,
    ) -> dict[str, Any]:
        """Create or reuse one content-derived tested-merge attestation."""

        qualification = self.qualifications.get(qualification_id)
        subject = self._qualification_subject(qualification)
        revision = self._merged_revision(subject["project"], merged_revision_id)
        self._require_exact_merge(subject, revision)
        input_document = self._input_document(qualification, revision)
        attestation_input_hash = self._hash_json(input_document)
        attestation_id = attestation_input_hash[:32]
        final_directory = self._attestation_directory(
            attestation_id,
            require_exists=False,
        )
        existing = self._read_existing(final_directory, attestation_id)
        if existing is not None:
            existing["cached"] = True
            return existing

        manifest = {
            "format": TESTED_MERGE_ATTESTATION_FORMAT,
            "key_format": TESTED_MERGE_ATTESTATION_KEY_FORMAT,
            "attestation_id": attestation_id,
            "cached": False,
            "qualification_id": qualification["qualification_id"],
            "qualification_manifest_sha256": qualification["manifest_sha256"],
            "qualification_status": qualification["status"],
            "all_selected_tests_passed": qualification["all_passed"],
            "selected_test_count": qualification["selected_test_count"],
            "passed_test_count": qualification["passed_test_count"],
            "failed_test_count": qualification["failed_test_count"],
            "error_test_count": qualification["error_test_count"],
            "test_targets": list(qualification["test_targets"]),
            "subject": subject,
            "merged_revision": revision,
            "state_identity_verified": True,
            "attestation_input_hash": attestation_input_hash,
            "interpretation": self._interpretation(qualification),
        }
        with tempfile.TemporaryDirectory(
            prefix=f".{attestation_id}-",
            dir=self.attestation_root,
        ) as temporary:
            temporary_directory = Path(temporary)
            self._write_json(temporary_directory / "attestation.json", manifest)
            self._verify_manifest(manifest, expected_id=attestation_id)
            with self._publication_lock(final_directory):
                existing = self._read_existing(final_directory, attestation_id)
                if existing is not None:
                    return existing
                if os.path.lexists(final_directory):
                    raise ArtifactIntegrityError(
                        f"tested merge attestation {attestation_id!r} already exists but is invalid"
                    )
                os.replace(temporary_directory, final_directory)
        return self.get(attestation_id)

    def get(self, attestation_id: str) -> dict[str, Any]:
        """Read and reverify one immutable tested-merge attestation."""

        directory = self._attestation_directory(attestation_id)
        path = directory / "attestation.json"
        manifest = self._read_json(path)
        self._verify_manifest(manifest, expected_id=attestation_id)
        result = dict(manifest)
        result["manifest_sha256"] = self._sha256_file(path)
        return result

    def _verify_manifest(
        self,
        manifest: dict[str, Any],
        *,
        expected_id: str,
    ) -> None:
        if manifest.get("format") != TESTED_MERGE_ATTESTATION_FORMAT:
            raise ArtifactIntegrityError("tested merge attestation format is invalid")
        if manifest.get("key_format") != TESTED_MERGE_ATTESTATION_KEY_FORMAT:
            raise ArtifactIntegrityError("tested merge attestation key format is invalid")
        if manifest.get("attestation_id") != expected_id:
            raise ArtifactIntegrityError("tested merge attestation identity is invalid")
        qualification_id = manifest.get("qualification_id")
        qualification = self.qualifications.get(qualification_id)
        subject = self._qualification_subject(qualification)
        revision_id = manifest.get("merged_revision", {}).get("revision_id")
        revision = self._merged_revision(subject["project"], revision_id)
        self._require_exact_merge(subject, revision)
        expected_input = self._input_document(qualification, revision)
        expected_hash = self._hash_json(expected_input)
        if manifest.get("attestation_input_hash") != expected_hash:
            raise ArtifactIntegrityError("tested merge attestation input hash is invalid")
        if expected_hash[:32] != expected_id:
            raise ArtifactIntegrityError("tested merge attestation ID is not content derived")
        expected = {
            "qualification_manifest_sha256": qualification["manifest_sha256"],
            "qualification_status": qualification["status"],
            "all_selected_tests_passed": qualification["all_passed"],
            "selected_test_count": qualification["selected_test_count"],
            "passed_test_count": qualification["passed_test_count"],
            "failed_test_count": qualification["failed_test_count"],
            "error_test_count": qualification["error_test_count"],
            "test_targets": list(qualification["test_targets"]),
            "subject": subject,
            "merged_revision": revision,
            "state_identity_verified": True,
            "interpretation": self._interpretation(qualification),
        }
        for field, value in expected.items():
            if manifest.get(field) != value:
                raise ArtifactIntegrityError(
                    f"tested merge attestation {field} evidence is invalid"
                )

    @staticmethod
    def _qualification_subject(qualification: dict[str, Any]) -> dict[str, Any]:
        subject = qualification.get("subject")
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
        if not isinstance(subject, dict) or set(subject) != required:
            raise ArtifactIntegrityError("candidate qualification subject shape is invalid")
        if subject.get("kind") != "virtual_merge_candidate":
            raise ArtifactIntegrityError("candidate qualification subject kind is invalid")
        if subject.get("committed_revision_id") is not None:
            raise ArtifactIntegrityError("candidate qualification cannot name a committed revision")
        return dict(subject)

    def _merged_revision(self, project: str, revision_id: Any) -> dict[str, Any]:
        if not isinstance(revision_id, str) or not revision_id:
            raise ValidationError(
                "INVALID_MERGED_REVISION_ID",
                "merged_revision_id must be a non-empty string",
            )
        row = self.workspace.db.connection.execute(
            """SELECT r.id, r.parent1_id, r.parent2_id, r.root_hash, p.name AS project
               FROM revisions r
               JOIN projects p ON p.id = r.project_id
               WHERE r.id = ? AND p.name = ?""",
            (revision_id, project),
        ).fetchone()
        if row is None:
            raise NotFoundError(
                f"merged revision {revision_id!r} does not belong to project {project!r}"
            )
        return {
            "revision_id": str(row["id"]),
            "project": str(row["project"]),
            "parent1_revision_id": row["parent1_id"],
            "parent2_revision_id": row["parent2_id"],
            "root_hash": str(row["root_hash"]),
        }

    @staticmethod
    def _require_exact_merge(
        subject: dict[str, Any],
        revision: dict[str, Any],
    ) -> None:
        expected = {
            "project": subject["project"],
            "parent1_revision_id": subject["target_head_revision_id"],
            "parent2_revision_id": subject["source_head_revision_id"],
            "root_hash": subject["merged_root_hash"],
        }
        mismatches = [field for field, value in expected.items() if revision.get(field) != value]
        if mismatches:
            raise ValidationError(
                "MERGED_REVISION_DOES_NOT_MATCH_QUALIFIED_CANDIDATE",
                "committed revision differs from the qualified candidate in: "
                + ", ".join(mismatches),
            )

    @staticmethod
    def _input_document(
        qualification: dict[str, Any],
        revision: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "format": TESTED_MERGE_ATTESTATION_KEY_FORMAT,
            "qualification_id": qualification["qualification_id"],
            "qualification_manifest_sha256": qualification["manifest_sha256"],
            "qualification_status": qualification["status"],
            "subject": qualification["subject"],
            "merged_revision": revision,
        }

    @staticmethod
    def _interpretation(qualification: dict[str, Any]) -> dict[str, Any]:
        return {
            "kind": "tested_merge_state_identity",
            "qualified_state_was_committed_exactly": True,
            "all_selected_tests_passed": qualification["all_passed"],
            "claims_complete_semantic_coverage": False,
            "claims_unselected_behavior": False,
            "claims_policy_admission": False,
            "claims_human_approval": False,
            "claims_production_readiness": False,
        }

    def _attestation_directory(
        self,
        attestation_id: str,
        *,
        require_exists: bool = True,
    ) -> Path:
        if not isinstance(attestation_id, str) or not TESTED_MERGE_ATTESTATION_ID.fullmatch(
            attestation_id
        ):
            raise ValidationError(
                "INVALID_TESTED_MERGE_ATTESTATION_ID",
                "attestation_id must be 32 lowercase hexadecimal characters",
            )
        directory = (self.attestation_root / attestation_id).resolve()
        if directory.parent != self.attestation_root:
            raise ValidationError(
                "INVALID_TESTED_MERGE_ATTESTATION_ID",
                "attestation_id escapes attestation root",
            )
        if require_exists and not directory.is_dir():
            raise NotFoundError(f"tested merge attestation {attestation_id!r} not found")
        return directory

    def _read_existing(
        self,
        directory: Path,
        attestation_id: str,
    ) -> dict[str, Any] | None:
        if not (directory / "attestation.json").is_file():
            return None
        try:
            return self.get(attestation_id)
        except (ArtifactIntegrityError, NotFoundError, ValidationError, TypeError):
            return None

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            value = read_bounded_regular_json(
                path,
                max_bytes=MAX_TESTED_MERGE_ATTESTATION_BYTES,
            )
        except RetainedArtifactReadError as exc:
            raise ArtifactIntegrityError(f"cannot read tested merge attestation: {exc}") from exc
        if not isinstance(value, dict):
            raise ArtifactIntegrityError("tested merge attestation root must be an object")
        return value

    @staticmethod
    def _hash_json(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
