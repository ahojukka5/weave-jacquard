from __future__ import annotations

from typing import Any

from weave_frontend import mcp_revision_evidence
from weave_frontend.revision_evidence import RevisionEvidenceService


class _Evidence:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def page(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((args, kwargs))
        return {
            "format": "weave-revision-evidence-page-v1",
            "page_id": "page-1",
        }


def test_revision_evidence_tool_forwards_exact_subject_and_bounds(monkeypatch) -> None:
    evidence = _Evidence()
    monkeypatch.setattr(mcp_revision_evidence, "revision_evidence", lambda: evidence)

    response = mcp_revision_evidence.revision_evidence_page(
        "demo",
        "revision-1",
        "test_batch",
        start_after_id="1" * 32,
        catalog_id="2" * 64,
        limit=7,
        scan_limit=19,
    )

    assert response["ok"] is True
    assert response["result"]["page_id"] == "page-1"
    assert evidence.calls == [
        (
            ("demo", "revision-1", "test_batch"),
            {
                "start_after_id": "1" * 32,
                "catalog_id": "2" * 64,
                "limit": 7,
                "scan_limit": 19,
            },
        )
    ]


def test_revision_evidence_factory_composes_shared_verified_services(
    tmp_path,
    monkeypatch,
) -> None:
    mcp_revision_evidence.revision_evidence.cache_clear()
    mcp_revision_evidence.workspace.cache_clear()
    mcp_revision_evidence.compiler_bridge.cache_clear()
    mcp_revision_evidence.test_runs.cache_clear()
    mcp_revision_evidence.test_batches.cache_clear()
    mcp_revision_evidence.merge_candidate_test_batches.cache_clear()
    mcp_revision_evidence.tested_merge_attestations.cache_clear()
    monkeypatch.setenv("WEAVE_DB_PATH", str(tmp_path / "evidence-factory.db"))
    monkeypatch.setenv("WEAVE_BUILD_ROOT", str(tmp_path / "builds"))
    monkeypatch.setenv("WEAVE_TEST_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("WEAVE_TEST_BATCH_ROOT", str(tmp_path / "batches"))
    monkeypatch.setenv("WEAVE_MERGE_TEST_RUN_ROOT", str(tmp_path / "qualifications"))
    monkeypatch.setenv(
        "WEAVE_MERGE_ATTESTATION_ROOT",
        str(tmp_path / "attestations"),
    )

    service = mcp_revision_evidence.revision_evidence()
    try:
        assert isinstance(service, RevisionEvidenceService)
        assert service.workspace is mcp_revision_evidence.workspace()
        assert service.qualifications is mcp_revision_evidence.merge_candidate_test_batches()
    finally:
        service.workspace.close()
        mcp_revision_evidence.revision_evidence.cache_clear()
        mcp_revision_evidence.tested_merge_attestations.cache_clear()
        mcp_revision_evidence.merge_candidate_test_batches.cache_clear()
        mcp_revision_evidence.test_batches.cache_clear()
        mcp_revision_evidence.test_runs.cache_clear()
        mcp_revision_evidence.compiler_bridge.cache_clear()
        mcp_revision_evidence.workspace.cache_clear()
