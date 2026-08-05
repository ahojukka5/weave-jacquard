from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from weave_frontend.artifacts.quota import ArtifactQuotaService, QuotaPublicationLockMixin
from weave_frontend.artifacts.storage import ArtifactStorageService
from weave_frontend.compiler import CompilerBridge as BaseCompilerBridge
from weave_frontend.errors import ArtifactQuotaExceededError
from weave_frontend.runtime import (
    CompilerBridge,
    TestBatchService,
    TestedMergeAttestationService,
    TestRunService,
)
from weave_frontend.test_batches import TestBatchService as BaseTestBatchService
from weave_frontend.test_runs import TestRunService as BaseTestRunService
from weave_frontend.tested_merge_attestations import (
    TestedMergeAttestationService as BaseTestedMergeAttestationService,
)
from weave_frontend.verified_merge_candidate_build import MergeCandidateBuildService
from weave_frontend.verified_merge_candidate_test_runs import (
    MergeCandidateTestBatchService,
)


def _quota(root: Path, *, max_bytes: int) -> ArtifactQuotaService:
    return ArtifactQuotaService(
        ArtifactStorageService({"test_runs": root}),
        lock_path=root.parent / "quota.lock",
        max_bytes=max_bytes,
    )


def test_quota_bridge_forwards_evidence_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def base_build(
        self: BaseCompilerBridge,
        project: str,
        document: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        captured.update(kwargs)
        return {"build_id": "a" * 32}

    bridge = CompilerBridge.__new__(CompilerBridge)
    bridge._weavec_capabilities = SimpleNamespace(
        require=lambda **kwargs: {"_jacquard_identity": {"format": "test"}}
    )
    monkeypatch.setattr(bridge, "_compiler_path", lambda: tmp_path / "weavec")
    monkeypatch.setattr(BaseCompilerBridge, "build", base_build)

    result = bridge.build(
        "demo",
        "main.weave",
        evidence_profile="full",
    )

    assert captured["evidence_profile"] == "full"
    assert result["compiler_capabilities"] == {"format": "test"}


def test_production_wrappers_preserve_base_service_contracts() -> None:
    assert issubclass(TestRunService, BaseTestRunService)
    assert issubclass(TestBatchService, BaseTestBatchService)
    assert issubclass(
        TestedMergeAttestationService,
        BaseTestedMergeAttestationService,
    )
    assert MergeCandidateBuildService.__name__ == "MergeCandidateBuildService"
    assert MergeCandidateTestBatchService.__name__ == ("MergeCandidateTestBatchService")


class _ParentPublication:
    def __init__(self) -> None:
        self.events: list[str] = []

    @contextmanager
    def _publication_lock(self, final: Path) -> Iterator[None]:
        self.events.append(f"enter:{final.name}")
        try:
            yield
        finally:
            self.events.append(f"exit:{final.name}")


class _QuotaPublication(QuotaPublicationLockMixin, _ParentPublication):
    artifact_quota_family = "test_runs"


def test_quota_mixin_admits_before_parent_publication_lock(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    root.mkdir()
    final = root / ("a" * 32)
    stage = root / f".{final.name}-stage"
    stage.mkdir()
    (stage / "artifact").write_bytes(b"abc")
    service = _QuotaPublication()
    service.artifact_quota = _quota(root, max_bytes=3)

    with service._publication_lock(final):
        service.events.append("publish")

    assert service.events == [
        f"enter:{final.name}",
        "publish",
        f"exit:{final.name}",
    ]


def test_quota_mixin_rejects_before_parent_publication_lock(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    root.mkdir()
    final = root / ("a" * 32)
    stage = root / f".{final.name}-stage"
    stage.mkdir()
    (stage / "artifact").write_bytes(b"abcd")
    service = _QuotaPublication()
    service.artifact_quota = _quota(root, max_bytes=3)

    with pytest.raises(ArtifactQuotaExceededError), service._publication_lock(final):
        raise AssertionError("overflowing publication unexpectedly entered")

    assert service.events == []
