from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from weave_frontend.database import Database
from weave_frontend.errors import ArtifactIntegrityError, ValidationError
from weave_frontend.tested_merge_attestations import TestedMergeAttestationService

BASE = "revision-base"
TARGET = "revision-target"
SOURCE = "revision-source"
MERGED = "revision-merged"
ROOT = "a" * 64
QUALIFICATION_ID = "b" * 32
QUALIFICATION_HASH = "c" * 64
PREVIEW_ID = "d" * 64


class _Workspace:
    def __init__(self, path: Path) -> None:
        self.db = Database(path)
        connection = self.db.connection
        connection.execute(
            "INSERT INTO projects(id, name) VALUES (?, ?)",
            ("project-id", "demo"),
        )
        for revision_id, parent1, parent2, root_hash in (
            (BASE, None, None, "0" * 64),
            (TARGET, BASE, None, "1" * 64),
            (SOURCE, BASE, None, "2" * 64),
            (MERGED, TARGET, SOURCE, ROOT),
        ):
            connection.execute(
                """INSERT INTO revisions(
                       id, project_id, parent1_id, parent2_id,
                       message, author, root_hash
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    revision_id,
                    "project-id",
                    parent1,
                    parent2,
                    "test revision",
                    "tester",
                    root_hash,
                ),
            )
        connection.commit()

    def close(self) -> None:
        self.db.close()


class _Qualifications:
    def __init__(self, *, status: str = "passed") -> None:
        self.status = status
        self.manifest_hash = QUALIFICATION_HASH

    def get(self, qualification_id: str) -> dict[str, Any]:
        assert qualification_id == QUALIFICATION_ID
        all_passed = self.status == "passed"
        failed_count = 1 if self.status == "failed" else 0
        error_count = 1 if self.status == "incomplete" else 0
        passed_count = 1 if all_passed else 0
        return {
            "qualification_id": QUALIFICATION_ID,
            "manifest_sha256": self.manifest_hash,
            "status": self.status,
            "all_passed": all_passed,
            "selected_test_count": 1,
            "passed_test_count": passed_count,
            "failed_test_count": failed_count,
            "error_test_count": error_count,
            "test_targets": ["smoke"],
            "subject": {
                "kind": "virtual_merge_candidate",
                "project": "demo",
                "target_branch": "main",
                "source_branch": "feature",
                "base_revision_id": BASE,
                "target_head_revision_id": TARGET,
                "source_head_revision_id": SOURCE,
                "preview_id": PREVIEW_ID,
                "merged_root_hash": ROOT,
                "committed_revision_id": None,
            },
        }


def test_attestation_links_exact_qualified_candidate_to_merge(tmp_path: Path) -> None:
    workspace = _Workspace(tmp_path / "jacquard.db")
    service = TestedMergeAttestationService(
        workspace,
        _Qualifications(),
        attestation_root=tmp_path / "attestations",
    )
    try:
        first = service.attest(QUALIFICATION_ID, MERGED)
        repeated = service.attest(QUALIFICATION_ID, MERGED)
        reread = service.get(first["attestation_id"])

        assert first["state_identity_verified"] is True
        assert first["qualification_status"] == "passed"
        assert first["all_selected_tests_passed"] is True
        assert first["merged_revision"] == {
            "revision_id": MERGED,
            "project": "demo",
            "parent1_revision_id": TARGET,
            "parent2_revision_id": SOURCE,
            "root_hash": ROOT,
        }
        assert first["interpretation"] == {
            "kind": "tested_merge_state_identity",
            "qualified_state_was_committed_exactly": True,
            "all_selected_tests_passed": True,
            "claims_complete_semantic_coverage": False,
            "claims_unselected_behavior": False,
            "claims_policy_admission": False,
            "claims_human_approval": False,
            "claims_production_readiness": False,
        }
        assert repeated["attestation_id"] == first["attestation_id"]
        assert repeated["cached"] is True
        assert reread["manifest_sha256"] == first["manifest_sha256"]
    finally:
        workspace.close()


def test_failed_qualification_is_attested_without_becoming_ready(tmp_path: Path) -> None:
    workspace = _Workspace(tmp_path / "jacquard.db")
    service = TestedMergeAttestationService(
        workspace,
        _Qualifications(status="failed"),
        attestation_root=tmp_path / "attestations",
    )
    try:
        result = service.attest(QUALIFICATION_ID, MERGED)

        assert result["qualification_status"] == "failed"
        assert result["all_selected_tests_passed"] is False
        assert result["failed_test_count"] == 1
        assert result["state_identity_verified"] is True
        assert result["interpretation"]["all_selected_tests_passed"] is False
        assert result["interpretation"]["claims_policy_admission"] is False
    finally:
        workspace.close()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("parent1_id", BASE),
        ("parent2_id", BASE),
        ("root_hash", "f" * 64),
    ],
)
def test_attestation_rejects_nonmatching_merge_revision(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    workspace = _Workspace(tmp_path / "jacquard.db")
    workspace.db.connection.execute(
        f"UPDATE revisions SET {field} = ? WHERE id = ?",
        (value, MERGED),
    )
    workspace.db.connection.commit()
    service = TestedMergeAttestationService(
        workspace,
        _Qualifications(),
        attestation_root=tmp_path / "attestations",
    )
    try:
        with pytest.raises(ValidationError) as raised:
            service.attest(QUALIFICATION_ID, MERGED)
        assert (
            raised.value.code
            == "MERGED_REVISION_DOES_NOT_MATCH_QUALIFIED_CANDIDATE"
        )
    finally:
        workspace.close()


def test_attestation_rejects_tampered_manifest_and_qualification(tmp_path: Path) -> None:
    workspace = _Workspace(tmp_path / "jacquard.db")
    qualifications = _Qualifications()
    service = TestedMergeAttestationService(
        workspace,
        qualifications,
        attestation_root=tmp_path / "attestations",
    )
    try:
        result = service.attest(QUALIFICATION_ID, MERGED)
        path = (
            tmp_path
            / "attestations"
            / result["attestation_id"]
            / "attestation.json"
        )
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["all_selected_tests_passed"] = False
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(ArtifactIntegrityError, match="all_selected_tests_passed"):
            service.get(result["attestation_id"])

        manifest["all_selected_tests_passed"] = True
        path.write_text(json.dumps(manifest), encoding="utf-8")
        qualifications.manifest_hash = "0" * 64
        with pytest.raises(ArtifactIntegrityError, match="input hash"):
            service.get(result["attestation_id"])
    finally:
        workspace.close()
