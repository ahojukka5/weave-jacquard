"""Final integrity and quota rules for virtual candidate test qualifications."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import ValidationError
from .merge_candidate_test_runs import (
    MergeCandidateTestBatchService as _BaseMergeCandidateTestBatchService,
)
from .quota_publication import QuotaPublicationLockMixin


class MergeCandidateTestBatchService(
    QuotaPublicationLockMixin,
    _BaseMergeCandidateTestBatchService,
):
    """Verify artifact-free errors and enforce aggregate qualification storage."""

    artifact_quota_family = "candidate_test_qualifications"

    @classmethod
    def _verify_artifacts(
        cls,
        manifest: dict[str, Any],
        directory: Path,
    ) -> None:
        artifacts = manifest.get("artifacts")
        results = manifest.get("results")
        all_build_errors = (
            isinstance(results, list)
            and bool(results)
            and all(
                isinstance(item, dict) and item.get("outcome") == "error"
                for item in results
            )
        )
        if artifacts == {} and all_build_errors:
            if manifest.get("artifact_sha256") != {}:
                raise ValidationError(
                    "INVALID_BUILD_MANIFEST",
                    "artifact-free candidate qualification must have no artifact hashes",
                )
            return
        super()._verify_artifacts(manifest, directory)
