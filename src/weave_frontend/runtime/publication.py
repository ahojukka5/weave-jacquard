"""Concrete runtime publishers with aggregate artifact quota admission."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..artifacts.quota import QuotaPublicationLockMixin, artifact_quota_admission
from ..compiler import CompilerBridge as _CompilerBridge
from ..compiler import WeavecCapabilities
from ..test_batches import TestBatchService as _TestBatchService
from ..test_runs import TestRunService as _TestRunService
from ..tested_merge_attestations import (
    TestedMergeAttestationService as _TestedMergeAttestationService,
)


class CompilerBridge(_CompilerBridge):
    """Publish compatible committed builds only after aggregate quota admission."""

    def capability_registry(self) -> dict[str, Any]:
        """Return the validated compiler-authoritative capability document."""

        capabilities = getattr(self, "_weavec_capabilities", None)
        compiler = self._compiler_path()
        if capabilities is None:
            capabilities = WeavecCapabilities(
                compiler,
                environment_fallback=False,
            )
            self._weavec_capabilities = capabilities
        return capabilities.load()

    def build(
        self,
        project: str,
        document: str,
        *,
        additional_documents: list[str] | None = None,
        branch: str = "main",
        revision_id: str | None = None,
        target: str | None = None,
        evidence_profile: str | None = None,
    ) -> dict[str, Any]:
        """Build only through an advertised final-compiler public contract."""

        capabilities = getattr(self, "_weavec_capabilities", None)
        compiler = self._compiler_path()
        if capabilities is None:
            capabilities = WeavecCapabilities(
                compiler,
                environment_fallback=False,
            )
            self._weavec_capabilities = capabilities
        registry = capabilities.require(
            command="build",
            protocols=(
                "weavec-build-manifest-v1",
                "weavec-diagnostics-v1",
                "weavec-compilation-trace-v1",
                "weave-wir-core-v2",
            ),
            target=target,
        )
        result = super().build(
            project,
            document,
            additional_documents=additional_documents,
            branch=branch,
            revision_id=revision_id,
            target=target,
            evidence_profile=evidence_profile,
        )
        result["compiler_capabilities"] = registry["_jacquard_identity"]
        return result

    def _publish_directory(self, temporary: Path, final: Path) -> None:
        with artifact_quota_admission(
            self,
            family="committed_builds",
            temporary=temporary,
            final=final,
        ):
            super()._publish_directory(temporary, final)


class TestBatchService(QuotaPublicationLockMixin, _TestBatchService):
    """Publish immutable test batches only while holding the aggregate quota lock."""

    artifact_quota_family = "test_batches"


class TestRunService(QuotaPublicationLockMixin, _TestRunService):
    """Publish immutable test runs only while holding the aggregate quota lock."""

    artifact_quota_family = "test_runs"


class TestedMergeAttestationService(
    QuotaPublicationLockMixin,
    _TestedMergeAttestationService,
):
    """Publish attestations only while holding the aggregate quota lock."""

    artifact_quota_family = "tested_merge_attestations"


__all__ = [
    "CompilerBridge",
    "TestBatchService",
    "TestRunService",
    "TestedMergeAttestationService",
]
