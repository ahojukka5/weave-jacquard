"""Bounded caller-ordered batches for guarded quarantine deletion."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ...artifacts.retention import hash_json, is_sha256
from ...errors import ValidationError, WeaveFrontendError
from .deletion import ArtifactQuarantineDeleteService

ARTIFACT_QUARANTINE_DELETE_BATCH_FORMAT = "weave-artifact-quarantine-delete-batch-v1"
MAX_ARTIFACT_QUARANTINE_DELETE_BATCH_ENTRIES = 100
_REQUIRED_ENTRY_KEYS = {
    "quarantine_id",
    "manifest_id",
    "plan_id",
    "verification_id",
    "minimum_holding_seconds",
    "as_of_unix_ns",
}


class ArtifactQuarantineDeleteBatchService:
    """Delete a bounded explicit selection with independent ordered outcomes."""

    def __init__(self, reconciliation: Any) -> None:
        self.delete_service = ArtifactQuarantineDeleteService(reconciliation)

    def delete_batch(
        self,
        entries: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Run an exact batch without claiming partial success is complete."""

        normalized = self._normalize_entries(entries)
        batch_id = hash_json(
            {
                "format": ARTIFACT_QUARANTINE_DELETE_BATCH_FORMAT,
                "entries": normalized,
            }
        )
        outcomes: list[dict[str, Any]] = []
        for index, entry in enumerate(normalized):
            identity = {
                "index": index,
                "quarantine_id": entry["quarantine_id"],
                "manifest_id": entry["manifest_id"],
                "plan_id": entry["plan_id"],
                "verification_id": entry["verification_id"],
            }
            try:
                result = self.delete_service.delete(**entry)
            except WeaveFrontendError as exc:
                if isinstance(exc, ValidationError):
                    error = exc.as_dict()
                else:
                    error = {
                        "code": type(exc).__name__,
                        "message": str(exc),
                    }
                outcomes.append({**identity, "ok": False, "error": error})
            else:
                outcomes.append({**identity, "ok": True, "result": result})

        succeeded = sum(item["ok"] for item in outcomes)
        failed = len(outcomes) - succeeded
        identity = {
            "format": ARTIFACT_QUARANTINE_DELETE_BATCH_FORMAT,
            "batch_id": batch_id,
            "complete": failed == 0,
            "mutation": "delete-batch",
            "requested": len(outcomes),
            "succeeded": succeeded,
            "failed": failed,
            "outcomes": outcomes,
            "limits": {
                "entries": MAX_ARTIFACT_QUARANTINE_DELETE_BATCH_ENTRIES,
            },
        }
        return {**identity, "batch_result_id": hash_json(identity)}

    @staticmethod
    def _normalize_entries(
        entries: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        if isinstance(entries, (str, bytes)) or not isinstance(entries, Sequence):
            raise ValidationError(
                "ARTIFACT_QUARANTINE_DELETE_BATCH_INVALID",
                "delete batch entries must be an ordered array",
            )
        if not entries or len(entries) > MAX_ARTIFACT_QUARANTINE_DELETE_BATCH_ENTRIES:
            raise ValidationError(
                "ARTIFACT_QUARANTINE_DELETE_BATCH_LIMIT_EXCEEDED",
                "delete batch must contain between one and the bounded maximum entries",
            )
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for value in entries:
            if not isinstance(value, Mapping) or set(value) != _REQUIRED_ENTRY_KEYS:
                raise ValidationError(
                    "ARTIFACT_QUARANTINE_DELETE_BATCH_INVALID",
                    "delete batch entry has invalid or missing fields",
                )
            entry = dict(value)
            for name in (
                "quarantine_id",
                "manifest_id",
                "plan_id",
                "verification_id",
            ):
                if not is_sha256(entry[name]):
                    raise ValidationError(
                        "ARTIFACT_QUARANTINE_DELETE_BATCH_INVALID",
                        f"{name} must be 64 lowercase hexadecimal characters",
                    )
            for name in ("minimum_holding_seconds", "as_of_unix_ns"):
                item = entry[name]
                if isinstance(item, bool) or not isinstance(item, int) or item < 0:
                    raise ValidationError(
                        "ARTIFACT_QUARANTINE_DELETE_BATCH_INVALID",
                        f"{name} must be a non-negative integer",
                    )
            if entry["quarantine_id"] in seen:
                raise ValidationError(
                    "ARTIFACT_QUARANTINE_DELETE_BATCH_DUPLICATE",
                    "delete batch contains a duplicate quarantine identity",
                )
            seen.add(entry["quarantine_id"])
            normalized.append(entry)
        return normalized


__all__ = [
    "ARTIFACT_QUARANTINE_DELETE_BATCH_FORMAT",
    "MAX_ARTIFACT_QUARANTINE_DELETE_BATCH_ENTRIES",
    "ArtifactQuarantineDeleteBatchService",
]
