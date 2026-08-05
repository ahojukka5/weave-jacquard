"""Production test-run service with aggregate artifact quota admission."""

from __future__ import annotations

from .artifacts.quota import QuotaPublicationLockMixin
from .test_runs import TestRunService as _TestRunService


class TestRunService(QuotaPublicationLockMixin, _TestRunService):
    """Publish immutable test runs only while holding the aggregate quota lock."""

    artifact_quota_family = "test_runs"


__all__ = ["TestRunService"]
