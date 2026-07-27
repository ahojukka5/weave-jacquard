from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from weave_frontend import SExpressionWorkspace, ValidationError
from weave_frontend.errors import ArtifactIntegrityError
from weave_frontend.revision_evidence import RevisionEvidenceService


class _EvidenceStore:
    def __init__(
        self,
        root: Path,
        root_attribute: str,
        manifest_name: str,
        records: dict[str, dict[str, Any] | Exception],
    ) -> None:
        root.mkdir(parents=True)
        setattr(self, root_attribute, root)
        self.records = records
        self.calls: list[str] = []
        for evidence_id in records:
            directory = root / evidence_id
            directory.mkdir()
            (directory / manifest_name).write_text("{}\n", encoding="utf-8")

    def get(self, evidence_id: str) -> dict[str, Any]:
        self.calls.append(evidence_id)
        value = self.records[evidence_id]
        if isinstance(value, Exception):
            raise value
        return dict(value)


class _Qualifications:
    def __init__(self, records: dict[str, dict[str, Any]]) -> None:
        self.records = records
        self.calls: list[str] = []

    def get(self, qualification_id: str) -> dict[str, Any]:
        self.calls.append(qualification_id)
        return dict(self.records[qualification_id])


def _id(value: int) -> str:
    return f"{value:032x}"


def _workspace(path: Path) -> tuple[SExpressionWorkspace, str]:
    workspace = SExpressionWorkspace(path)
    _, revision_id = workspace.initialize("demo")
    return workspace, revision_id


def _service(
    tmp_path: Path,
    workspace: SExpressionWorkspace,
    *,
    builds: dict[str, dict[str, Any] | Exception] | None = None,
    runs: dict[str, dict[str, Any] | Exception] | None = None,
    batches: dict[str, dict[str, Any] | Exception] | None = None,
    attestations: dict[str, dict[str, Any] | Exception] | None = None,
    qualifications: dict[str, dict[str, Any]] | None = None,
) -> tuple[RevisionEvidenceService, dict[str, Any]]:
    build_store = _EvidenceStore(
        tmp_path / "builds",
        "build_root",
        "manifest.json",
        builds or {},
    )
    run_store = _EvidenceStore(
        tmp_path / "runs",
        "run_root",
        "run-manifest.json",
        runs or {},
    )
    batch_store = _EvidenceStore(
        tmp_path / "batches",
        "batch_root",
        "batch-manifest.json",
        batches or {},
    )
    attestation_store = _EvidenceStore(
        tmp_path / "attestations",
        "attestation_root",
        "attestation.json",
        attestations or {},
    )
    qualification_store = _Qualifications(qualifications or {})
    service = RevisionEvidenceService(
        workspace,
        build_store,
        run_store,
        batch_store,
        qualification_store,
        attestation_store,
    )
    return service, {
        "builds": build_store,
        "runs": run_store,
        "batches": batch_store,
        "attestations": attestation_store,
        "qualifications": qualification_store,
    }


def test_build_evidence_pages_are_sparse_stable_and_verified_once(tmp_path: Path) -> None:
    workspace, revision_id = _workspace(tmp_path / "workspace.db")
    foreign_id = _id(1)
    first_id = _id(2)
    second_id = _id(3)
    builds = {
        foreign_id: {
            "build_id": foreign_id,
            "project": "other",
            "revision_id": revision_id,
        },
        first_id: {
            "build_id": first_id,
            "status": "succeeded",
            "project": "demo",
            "revision_id": revision_id,
            "document": "main.weave",
            "documents": ["main.weave"],
            "target": "native",
            "compiler_sha256": "a" * 64,
            "manifest_sha256": "b" * 64,
        },
        second_id: {
            "build_id": second_id,
            "status": "failed",
            "project": "demo",
            "revision_id": revision_id,
            "document": "main.weave",
            "documents": ["main.weave"],
            "target": "native",
            "compiler_sha256": "a" * 64,
            "manifest_sha256": "c" * 64,
        },
    }
    service, stores = _service(tmp_path, workspace, builds=builds)
    with workspace:
        first = service.page(
            "demo",
            revision_id,
            "build",
            limit=1,
            scan_limit=2,
        )
        assert first["matched_evidence_count"] == 1
        assert first["scanned_member_count"] == 2
        assert first["has_more"] is True
        assert first["next_after_id"] == first_id
        assert [node["kind"] for node in first["nodes"]] == ["revision", "build"]
        assert first["nodes"][1]["evidence_id"] == first_id
        assert first["edges"] == [
            {
                "from": f"build:{first_id}",
                "relation": "built_from_revision",
                "to": f"revision:{revision_id}",
            }
        ]
        assert stores["builds"].calls == [foreign_id, first_id]

        second = service.page(
            "demo",
            revision_id,
            "build",
            start_after_id=first["next_after_id"],
            catalog_id=first["catalog_id"],
            limit=1,
            scan_limit=1,
        )
        assert second["nodes"][1]["evidence_id"] == second_id
        assert second["has_more"] is False
        assert stores["builds"].calls == [foreign_id, first_id, second_id]
        assert len(first["page_id"]) == 64

        new_id = _id(4)
        new_directory = stores["builds"].build_root / new_id
        new_directory.mkdir()
        (new_directory / "manifest.json").write_text("{}\n", encoding="utf-8")
        with pytest.raises(ValidationError) as raised:
            service.page(
                "demo",
                revision_id,
                "build",
                catalog_id=first["catalog_id"],
            )
        assert raised.value.code == "STALE_REVISION_EVIDENCE_CATALOG"


def test_run_and_batch_graphs_expose_cross_kind_edges(tmp_path: Path) -> None:
    workspace, revision_id = _workspace(tmp_path / "workspace.db")
    build_id = _id(10)
    run_id = _id(11)
    batch_id = _id(12)
    runs = {
        run_id: {
            "run_id": run_id,
            "status": "passed",
            "passed": True,
            "project": "demo",
            "revision_id": revision_id,
            "test_target": "smoke",
            "definition_hash": "d" * 64,
            "build_id": build_id,
            "sandbox": {"policy_hash": "e" * 64},
            "manifest_sha256": "f" * 64,
        }
    }
    batches = {
        batch_id: {
            "batch_id": batch_id,
            "status": "passed",
            "all_passed": True,
            "project": "demo",
            "revision_id": revision_id,
            "test_targets": ["smoke"],
            "selected_test_count": 1,
            "passed_test_count": 1,
            "failed_test_count": 0,
            "error_test_count": 0,
            "sandbox": {"policy_hash": "e" * 64},
            "manifest_sha256": "1" * 64,
            "results": [{"test_target": "smoke", "run_id": run_id}],
        }
    }
    service, _ = _service(tmp_path, workspace, runs=runs, batches=batches)
    with workspace:
        run_page = service.page("demo", revision_id, "test_run")
        assert {
            "from": f"test_run:{run_id}",
            "relation": "used_build",
            "to": f"build:{build_id}",
        } in run_page["edges"]

        batch_page = service.page("demo", revision_id, "test_batch")
        assert {
            "from": f"test_batch:{batch_id}",
            "relation": "contains_run",
            "to": f"test_run:{run_id}",
        } in batch_page["edges"]
        assert batch_page["edge_note"].startswith("edges may reference")


def test_attestation_page_reaches_verified_virtual_candidate_evidence(
    tmp_path: Path,
) -> None:
    workspace, base_revision = _workspace(tmp_path / "workspace.db")
    with workspace:
        workspace.create_branch("demo", "feature")
        target_head = workspace.branch_head("demo", "main")
        source_head = workspace.branch_head("demo", "feature")
        merged = workspace.merge(
            "demo",
            target_branch="main",
            source_branch="feature",
        )
        revision_id = merged.revision_id
        build_id = _id(21)
        qualification_id = _id(22)
        attestation_id = _id(23)
        subject = {
            "kind": "virtual_merge_candidate",
            "project": "demo",
            "target_branch": "main",
            "source_branch": "feature",
            "base_revision_id": base_revision,
            "target_head_revision_id": target_head,
            "source_head_revision_id": source_head,
            "preview_id": "p" * 64,
            "merged_root_hash": workspace.db.hash_value({}),
            "committed_revision_id": None,
        }
        qualifications = {
            qualification_id: {
                "qualification_id": qualification_id,
                "status": "failed",
                "all_passed": False,
                "subject": subject,
                "test_targets": ["smoke"],
                "selected_test_count": 1,
                "passed_test_count": 0,
                "failed_test_count": 1,
                "error_test_count": 0,
                "manifest_sha256": "2" * 64,
                "builds": [
                    {
                        "build_target": "application",
                        "build_id": build_id,
                        "build_input_hash": "3" * 64,
                        "manifest_sha256": "4" * 64,
                        "status": "succeeded",
                    }
                ],
            }
        }
        attestations = {
            attestation_id: {
                "attestation_id": attestation_id,
                "qualification_id": qualification_id,
                "qualification_status": "failed",
                "all_selected_tests_passed": False,
                "state_identity_verified": True,
                "merged_revision": {
                    "project": "demo",
                    "revision_id": revision_id,
                },
                "manifest_sha256": "5" * 64,
            }
        }
        service, stores = _service(
            tmp_path,
            workspace,
            attestations=attestations,
            qualifications=qualifications,
        )
        page = service.page(
            "demo",
            revision_id,
            "tested_merge_attestation",
        )
        kinds = {node["kind"] for node in page["nodes"]}
        assert kinds == {
            "revision",
            "tested_merge_attestation",
            "merge_candidate_qualification",
            "merge_candidate_build",
        }
        assert {
            "from": f"tested_merge_attestation:{attestation_id}",
            "relation": "binds_qualification",
            "to": f"merge_candidate_qualification:{qualification_id}",
        } in page["edges"]
        assert {
            "from": f"merge_candidate_qualification:{qualification_id}",
            "relation": "used_candidate_build",
            "to": f"merge_candidate_build:{build_id}",
        } in page["edges"]
        assert stores["qualifications"].calls == [qualification_id]
        assert page["interpretation"]["claims_approval_or_readiness"] is False


def test_corrupt_members_are_bounded_and_paths_are_not_exposed(tmp_path: Path) -> None:
    workspace, revision_id = _workspace(tmp_path / "workspace.db")
    corrupt_id = _id(31)
    service, _ = _service(
        tmp_path,
        workspace,
        runs={corrupt_id: ArtifactIntegrityError("secret /server/path")},
    )
    with workspace:
        page = service.page("demo", revision_id, "test_run")
        assert page["matched_evidence_count"] == 0
        assert page["rejected"] == [
            {
                "evidence_id": corrupt_id,
                "error_code": "ARTIFACT_INTEGRITY_ERROR",
            }
        ]
        assert "/server/path" not in str(page)


@pytest.mark.parametrize(
    ("kind", "limit", "scan_limit", "code"),
    [
        ("unknown", 25, 100, "INVALID_REVISION_EVIDENCE_KIND"),
        ("build", 0, 100, "INVALID_REVISION_EVIDENCE_LIMIT"),
        ("build", 10, 5, "INVALID_REVISION_EVIDENCE_LIMIT"),
    ],
)
def test_invalid_evidence_requests_are_rejected(
    tmp_path: Path,
    kind: str,
    limit: int,
    scan_limit: int,
    code: str,
) -> None:
    workspace, revision_id = _workspace(tmp_path / "workspace.db")
    service, _ = _service(tmp_path, workspace)
    with workspace, pytest.raises(ValidationError) as raised:
        service.page(
            "demo",
            revision_id,
            kind,
            limit=limit,
            scan_limit=scan_limit,
        )
    assert raised.value.code == code
