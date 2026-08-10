"""Bounded inspection of verified immutable build diagnostics."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Protocol

from ..errors import ValidationError

MAX_DIAGNOSTIC_PAGE_SIZE = 200


class _BuildReader(Protocol):
    def get(self, build_id: str) -> dict[str, Any]: ...


class BuildInspectionService:
    """Read retained build evidence only after normal artifact verification."""

    def __init__(self, bridge: _BuildReader) -> None:
        self.bridge = bridge

    def diagnostics_page(
        self,
        build_id: str,
        *,
        start_index: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Return one bounded page of mapped diagnostics for a verified build."""

        self._validate_start_index(start_index)
        self._validate_limit(limit)
        build = self.bridge.get(build_id)
        diagnostics_path, expected_sha256 = self._diagnostics_artifact(build)
        diagnostics = self._read_diagnostics(
            diagnostics_path,
            expected_sha256=expected_sha256,
        )
        entries = diagnostics.get("entries")
        if not isinstance(entries, list) or not all(
            isinstance(entry, dict) for entry in entries
        ):
            raise ValidationError(
                "INVALID_BUILD_DIAGNOSTICS",
                "mapped build diagnostics entries must be an array of objects",
            )

        page = entries[start_index : start_index + limit]
        next_index = start_index + len(page)
        has_more = next_index < len(entries)
        return {
            "build_id": build_id,
            "status": build.get("status"),
            "revision_id": build.get("revision_id"),
            "project": build.get("project"),
            "branch": build.get("branch"),
            "document": build.get("document"),
            "documents": build.get("documents"),
            "returncode": build.get("returncode"),
            "protocol_valid": diagnostics.get("protocol_valid"),
            "protocol_error_count": self._list_count(diagnostics.get("protocol_errors")),
            "compiler": diagnostics.get("compiler"),
            "compiler_manifest": diagnostics.get("compiler_manifest"),
            "compiler_manifest_protocol_valid": diagnostics.get(
                "compiler_manifest_protocol_valid"
            ),
            "total_diagnostic_count": len(entries),
            "start_index": start_index,
            "limit": limit,
            "returned_count": len(page),
            "has_more": has_more,
            "next_index": next_index if has_more else None,
            "diagnostics": page,
        }

    @staticmethod
    def _diagnostics_artifact(build: dict[str, Any]) -> tuple[Path, str]:
        artifact_paths = build.get("artifact_paths")
        artifacts = build.get("artifacts")
        hashes = build.get("artifact_sha256")
        diagnostics_path = (
            artifact_paths.get("diagnostics")
            if isinstance(artifact_paths, dict)
            else None
        )
        relative = artifacts.get("diagnostics") if isinstance(artifacts, dict) else None
        expected_sha256 = hashes.get(relative) if isinstance(hashes, dict) else None
        if (
            not isinstance(diagnostics_path, str)
            or not diagnostics_path
            or not isinstance(relative, str)
            or not relative
            or not isinstance(expected_sha256, str)
            or len(expected_sha256) != 64
        ):
            raise ValidationError(
                "MISSING_BUILD_DIAGNOSTICS",
                "verified build manifest does not reference hashed mapped diagnostics",
            )
        return Path(diagnostics_path), expected_sha256

    @staticmethod
    def _read_diagnostics(path: Path, *, expected_sha256: str) -> dict[str, Any]:
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise ValidationError(
                "INVALID_BUILD_DIAGNOSTICS",
                f"cannot read mapped build diagnostics: {exc}",
            ) from exc
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise ValidationError(
                "CORRUPT_BUILD_ARTIFACT",
                "mapped build diagnostics checksum changed during inspection",
            )
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValidationError(
                "INVALID_BUILD_DIAGNOSTICS",
                f"cannot decode mapped build diagnostics: {exc}",
            ) from exc
        if not isinstance(value, dict):
            raise ValidationError(
                "INVALID_BUILD_DIAGNOSTICS",
                "mapped build diagnostics root must be an object",
            )
        if value.get("format") != "weave-build-diagnostics-v1":
            raise ValidationError(
                "INVALID_BUILD_DIAGNOSTICS",
                f"unsupported mapped diagnostics format: {value.get('format')!r}",
            )
        return value

    @staticmethod
    def _list_count(value: Any) -> int | None:
        return len(value) if isinstance(value, list) else None

    @staticmethod
    def _validate_start_index(start_index: int) -> None:
        if (
            isinstance(start_index, bool)
            or not isinstance(start_index, int)
            or start_index < 0
        ):
            raise ValidationError(
                "INVALID_DIAGNOSTIC_INDEX",
                "start_index must be a non-negative integer",
            )

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValidationError(
                "INVALID_DIAGNOSTIC_LIMIT",
                "limit must be an integer",
            )
        if limit < 1 or limit > MAX_DIAGNOSTIC_PAGE_SIZE:
            raise ValidationError(
                "INVALID_DIAGNOSTIC_LIMIT",
                f"limit must be between 1 and {MAX_DIAGNOSTIC_PAGE_SIZE}",
            )
