"""Final retained-metadata admission for virtual merge-candidate builds."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .bounded_merge_candidate_build import (
    MergeCandidateBuildService as _BoundedMergeCandidateBuildService,
)
from .errors import ArtifactIntegrityError
from .retained_artifact_io import (
    RetainedArtifactReadError,
    read_bounded_regular_json,
)

MAX_MERGE_CANDIDATE_BUILD_MANIFEST_BYTES = 4 * 1024 * 1024


class MergeCandidateBuildService(_BoundedMergeCandidateBuildService):
    """Admit candidate-build manifests through one bounded regular-file boundary."""

    @staticmethod
    def _read_manifest(path: Path) -> dict[str, Any]:
        try:
            value = read_bounded_regular_json(
                path,
                max_bytes=MAX_MERGE_CANDIDATE_BUILD_MANIFEST_BYTES,
            )
        except RetainedArtifactReadError as exc:
            raise ArtifactIntegrityError(
                f"cannot read merge candidate build manifest: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise ArtifactIntegrityError(
                "merge candidate build manifest root must be an object"
            )
        return value


__all__ = [
    "MAX_MERGE_CANDIDATE_BUILD_MANIFEST_BYTES",
    "MergeCandidateBuildService",
]
