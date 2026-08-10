"""Bounded discovery of verified immutable build manifests."""

from __future__ import annotations

import bisect
import hashlib
import json
from pathlib import Path
from typing import Any, Protocol

from ..compiler import BUILD_KEY_FORMAT, normalize_evidence_profile
from ..errors import NotFoundError, ValidationError

BUILD_LIST_FORMAT = "weave-build-list-page-v1"
BUILD_CATALOG_FORMAT = "weave-build-catalog-v1"
MAX_BUILD_LIST_PAGE_SIZE = 200


class _BuildBridge(Protocol):
    build_root: Path
    workspace: Any

    def get(self, build_id: str) -> dict[str, Any]: ...


class BuildDiscoveryService:
    """Page compact summaries only after normal stored-build verification."""

    def __init__(self, bridge: _BuildBridge) -> None:
        self.bridge = bridge

    def page(
        self,
        project: str,
        *,
        branch: str | None = None,
        revision_id: str | None = None,
        status: str | None = None,
        document: str | None = None,
        target: str | None = None,
        start_after_build_id: str | None = None,
        catalog_id: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Scan one bounded catalog page and return verified matching builds."""

        self.bridge.workspace.project_id(project)
        filters = self._validate_filters(
            branch=branch,
            revision_id=revision_id,
            status=status,
            document=document,
            target=target,
        )
        self._validate_limit(limit)
        self._validate_start_after(start_after_build_id)
        self._validate_catalog_id(catalog_id)

        build_ids = self._candidate_build_ids()
        current_catalog_id = self._catalog_id(build_ids)
        if catalog_id is not None and catalog_id != current_catalog_id:
            raise ValidationError(
                "STALE_BUILD_CATALOG",
                "stored build catalog membership changed after the previous page",
            )

        start_index = (
            bisect.bisect_right(build_ids, start_after_build_id)
            if start_after_build_id is not None
            else 0
        )
        scanned_ids = build_ids[start_index : start_index + limit]
        builds: list[dict[str, Any]] = []
        rejected: list[dict[str, str]] = []
        filtered_count = 0

        for build_id in scanned_ids:
            try:
                manifest = self.bridge.get(build_id)
                summary = self._summary(manifest, expected_build_id=build_id)
            except ValidationError as exc:
                rejected.append({"build_id": build_id, "code": exc.code})
                continue
            except NotFoundError:
                rejected.append({"build_id": build_id, "code": "BUILD_NOT_FOUND_DURING_SCAN"})
                continue

            if summary["project"] != project or not self._matches(summary, filters):
                filtered_count += 1
                continue
            builds.append(summary)

        next_after = scanned_ids[-1] if scanned_ids else start_after_build_id
        has_more = start_index + len(scanned_ids) < len(build_ids)
        return {
            "format": BUILD_LIST_FORMAT,
            "catalog_format": BUILD_CATALOG_FORMAT,
            "catalog_id": current_catalog_id,
            "catalog_scope": "build-root-membership",
            "catalog_build_count": len(build_ids),
            "project": project,
            "filters": filters,
            "start_after_build_id": start_after_build_id,
            "limit": limit,
            "scanned_count": len(scanned_ids),
            "returned_count": len(builds),
            "filtered_count": filtered_count,
            "rejected_count": len(rejected),
            "has_more": has_more,
            "next_after_build_id": next_after if has_more else None,
            "builds": builds,
            "rejected_builds": rejected,
        }

    def _candidate_build_ids(self) -> list[str]:
        try:
            entries = list(self.bridge.build_root.iterdir())
        except OSError as exc:
            raise ValidationError(
                "BUILD_CATALOG_UNAVAILABLE",
                f"cannot enumerate stored build root: {exc}",
            ) from exc

        result: list[str] = []
        for entry in entries:
            try:
                if not self._valid_build_id(entry.name) or entry.is_symlink():
                    continue
                manifest = entry / "manifest.json"
                is_directory = entry.is_dir()
                is_manifest = manifest.is_file() and not manifest.is_symlink()
            except OSError:
                continue
            if is_directory and is_manifest:
                result.append(entry.name)
        return sorted(result)

    @staticmethod
    def _catalog_id(build_ids: list[str]) -> str:
        payload = json.dumps(
            {"format": BUILD_CATALOG_FORMAT, "build_ids": build_ids},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(payload).hexdigest()

    def _summary(
        self,
        manifest: dict[str, Any],
        *,
        expected_build_id: str,
    ) -> dict[str, Any]:
        build_id = manifest.get("build_id")
        project = manifest.get("project")
        branch = manifest.get("branch")
        revision_id = manifest.get("revision_id")
        revision_hash = manifest.get("revision_hash")
        document = manifest.get("document")
        documents = manifest.get("documents")
        target = manifest.get("target")
        compiler_target = manifest.get("compiler_target")
        compiler_sha256 = manifest.get("compiler_sha256")
        build_key_format = manifest.get("build_key_format")
        artifacts = manifest.get("artifacts")

        if build_id != expected_build_id:
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                "verified build manifest ID changed during discovery",
            )
        self._require_string(project, "project")
        self._require_string(branch, "branch")
        self._require_string(revision_id, "revision_id")
        self._require_sha256(revision_hash, "revision_hash")
        self._require_string(document, "document")
        if (
            not isinstance(documents, list)
            or not documents
            or any(not isinstance(item, str) or not item for item in documents)
            or documents[0] != document
        ):
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                "build manifest documents must be non-empty strings led by document",
            )
        self._require_string(target, "target")
        if compiler_target is not None:
            self._require_string(compiler_target, "compiler_target")
        self._require_sha256(compiler_sha256, "compiler_sha256")
        self._require_string(build_key_format, "build_key_format")
        if not isinstance(artifacts, dict):
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                "build manifest artifacts must be an object",
            )

        self._require_revision_provenance(
            str(project),
            str(revision_id),
            str(revision_hash),
        )
        build_key_verified = False
        if build_key_format == BUILD_KEY_FORMAT:
            self._require_current_build_key(
                manifest,
                build_id=str(build_id),
                revision_id=str(revision_id),
                revision_hash=str(revision_hash),
                documents=list(documents),
                compiler_sha256=str(compiler_sha256),
                target=str(target),
            )
            build_key_verified = True

        return {
            "build_id": build_id,
            "status": manifest["status"],
            "evidence_profile": manifest.get("evidence_profile"),
            "project": project,
            "branch": branch,
            "revision_id": revision_id,
            "revision_hash": revision_hash,
            "revision_provenance_verified": True,
            "document": document,
            "documents": list(documents),
            "target": target,
            "compiler_target": compiler_target,
            "compiler_sha256": compiler_sha256,
            "build_key_format": build_key_format,
            "build_key_verified": build_key_verified,
            "returncode": manifest.get("returncode"),
            "compiler_diagnostics_protocol_valid": manifest.get(
                "compiler_diagnostics_protocol_valid"
            ),
            "compiler_manifest_protocol_valid": manifest.get("compiler_manifest_protocol_valid"),
            "executable_available": isinstance(artifacts.get("executable"), str),
            "diagnostics_available": isinstance(artifacts.get("diagnostics"), str),
        }

    def _require_revision_provenance(
        self,
        project: str,
        revision_id: str,
        revision_hash: str,
    ) -> None:
        row = self.bridge.workspace.db.connection.execute(
            """SELECT r.root_hash
               FROM revisions r
               JOIN projects p ON p.id = r.project_id
               WHERE r.id = ? AND p.name = ?""",
            (revision_id, project),
        ).fetchone()
        if row is None:
            raise ValidationError(
                "BUILD_REVISION_NOT_FOUND",
                "build manifest revision does not belong to its recorded project",
            )
        if str(row["root_hash"]) != revision_hash:
            raise ValidationError(
                "BUILD_REVISION_HASH_MISMATCH",
                "build manifest revision hash does not match immutable revision storage",
            )

    @classmethod
    def _require_current_build_key(
        cls,
        manifest: dict[str, Any],
        *,
        build_id: str,
        revision_id: str,
        revision_hash: str,
        documents: list[str],
        compiler_sha256: str,
        target: str,
    ) -> None:
        if "evidence_profile" not in manifest:
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                "current build key requires an explicit evidence profile",
            )
        evidence_profile = normalize_evidence_profile(manifest["evidence_profile"])
        sources = manifest.get("sources")
        artifact_hashes = manifest.get("artifact_sha256")
        if not isinstance(sources, list) or len(sources) != len(documents):
            raise ValidationError(
                "BUILD_SOURCE_METADATA_MISMATCH",
                "current build key requires one source metadata entry per document",
            )
        if not isinstance(artifact_hashes, dict):
            raise ValidationError(
                "BUILD_SOURCE_METADATA_MISMATCH",
                "current build key requires artifact hash metadata",
            )

        key_documents: list[dict[str, str]] = []
        for index, (document, source) in enumerate(zip(documents, sources, strict=True)):
            if not isinstance(source, dict) or source.get("document") != document:
                raise ValidationError(
                    "BUILD_SOURCE_METADATA_MISMATCH",
                    f"source metadata at index {index} does not match document order",
                )
            relative = source.get("source")
            source_sha256 = source.get("source_sha256")
            cls._require_string(
                relative,
                f"sources[{index}].source",
                code="BUILD_SOURCE_METADATA_MISMATCH",
            )
            cls._require_sha256(
                source_sha256,
                f"sources[{index}].source_sha256",
                code="BUILD_SOURCE_METADATA_MISMATCH",
            )
            if artifact_hashes.get(relative) != source_sha256:
                raise ValidationError(
                    "BUILD_SOURCE_METADATA_MISMATCH",
                    f"source metadata hash does not match artifact hash at index {index}",
                )
            key_documents.append({"document": document, "source_sha256": str(source_sha256)})

        if manifest.get("source_sha256") != key_documents[0]["source_sha256"]:
            raise ValidationError(
                "BUILD_SOURCE_METADATA_MISMATCH",
                "primary source hash does not match the first ordered source",
            )

        output_limit = manifest.get("compiler_output_limit_bytes")
        if isinstance(output_limit, bool) or not isinstance(output_limit, int) or output_limit <= 0:
            raise ValidationError(
                "BUILD_SOURCE_METADATA_MISMATCH",
                "current build key requires a positive compiler output limit",
            )

        payload = {
            "format": BUILD_KEY_FORMAT,
            "revision_hash": revision_hash,
            "revision_id": revision_id,
            "documents": key_documents,
            "compiler_sha256": compiler_sha256,
            "compiler_output_limit_bytes": output_limit,
            "target": target,
            "evidence_profile": evidence_profile,
        }
        expected_build_id = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:32]
        if expected_build_id != build_id:
            raise ValidationError(
                "BUILD_KEY_MISMATCH",
                "current build manifest inputs do not reproduce the stored build ID",
            )

    @staticmethod
    def _matches(summary: dict[str, Any], filters: dict[str, Any]) -> bool:
        if filters["branch"] is not None and summary["branch"] != filters["branch"]:
            return False
        if filters["revision_id"] is not None and summary["revision_id"] != filters["revision_id"]:
            return False
        if filters["status"] is not None and summary["status"] != filters["status"]:
            return False
        if filters["document"] is not None and filters["document"] not in summary["documents"]:
            return False
        return filters["target"] is None or summary["target"] == filters["target"]

    @classmethod
    def _validate_filters(
        cls,
        *,
        branch: str | None,
        revision_id: str | None,
        status: str | None,
        document: str | None,
        target: str | None,
    ) -> dict[str, Any]:
        for name, value in (
            ("branch", branch),
            ("revision_id", revision_id),
            ("document", document),
            ("target", target),
        ):
            if value is not None:
                cls._require_string(value, name, code="INVALID_BUILD_LIST_FILTER")
        if status not in {None, "succeeded", "failed"}:
            raise ValidationError(
                "INVALID_BUILD_LIST_FILTER",
                "status must be 'succeeded', 'failed', or null",
            )
        return {
            "branch": branch,
            "revision_id": revision_id,
            "status": status,
            "document": document,
            "target": target,
        }

    @staticmethod
    def _require_string(
        value: Any,
        name: str,
        *,
        code: str = "INVALID_BUILD_MANIFEST",
    ) -> None:
        if not isinstance(value, str) or not value:
            raise ValidationError(code, f"{name} must be a non-empty string")

    @staticmethod
    def _require_sha256(
        value: Any,
        name: str,
        *,
        code: str = "INVALID_BUILD_MANIFEST",
    ) -> None:
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ValidationError(code, f"{name} must be lowercase SHA-256")

    @classmethod
    def _validate_start_after(cls, value: str | None) -> None:
        if value is not None and not cls._valid_build_id(value):
            raise ValidationError(
                "INVALID_BUILD_LIST_CURSOR",
                "start_after_build_id must be 32 lowercase hexadecimal characters",
            )

    @staticmethod
    def _validate_catalog_id(value: str | None) -> None:
        if value is not None and (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ValidationError(
                "INVALID_BUILD_CATALOG_ID",
                "catalog_id must be 64 lowercase hexadecimal characters",
            )

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValidationError("INVALID_BUILD_LIST_LIMIT", "limit must be an integer")
        if limit < 1 or limit > MAX_BUILD_LIST_PAGE_SIZE:
            raise ValidationError(
                "INVALID_BUILD_LIST_LIMIT",
                f"limit must be between 1 and {MAX_BUILD_LIST_PAGE_SIZE}",
            )

    @staticmethod
    def _valid_build_id(value: Any) -> bool:
        return (
            isinstance(value, str)
            and len(value) == 32
            and all(character in "0123456789abcdef" for character in value)
        )
