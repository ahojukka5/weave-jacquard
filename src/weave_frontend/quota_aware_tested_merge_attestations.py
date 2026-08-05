"""Production tested-merge attestations with artifact quota admission."""

from __future__ import annotations

from .artifacts.quota import QuotaPublicationLockMixin
from .tested_merge_attestations import (
    TestedMergeAttestationService as _TestedMergeAttestationService,
)


class TestedMergeAttestationService(
    QuotaPublicationLockMixin,
    _TestedMergeAttestationService,
):
    """Publish attestations only while holding the aggregate quota lock."""

    artifact_quota_family = "tested_merge_attestations"


__all__ = ["TestedMergeAttestationService"]
