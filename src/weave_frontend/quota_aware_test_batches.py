"""Production test-batch service with aggregate artifact quota admission."""

from __future__ import annotations

from .artifacts.quota import QuotaPublicationLockMixin
from .test_batches import TestBatchService as _TestBatchService


class TestBatchService(QuotaPublicationLockMixin, _TestBatchService):
    """Publish immutable test batches only while holding the aggregate quota lock."""

    artifact_quota_family = "test_batches"


__all__ = ["TestBatchService"]
