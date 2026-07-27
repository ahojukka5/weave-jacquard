"""Build-target registry aware of every reserved project metadata class."""

from __future__ import annotations

from typing import Any

from .concurrent_build_targets import BuildTargetRegistry as _BaseBuildTargetRegistry
from .errors import NotFoundError, ValidationError
from .project_metadata import is_project_metadata_document
from .sexpr import JsonObject
from .test_target_validation import require_build_target_not_referenced


class BuildTargetRegistry(_BaseBuildTargetRegistry):
    """Race-safe build targets that never treat project metadata as source."""

    @classmethod
    def _validate_document_set(
        cls,
        document: str,
        additional_documents: list[str] | None,
    ) -> list[str]:
        documents = super()._validate_document_set(document, additional_documents)
        if any(is_project_metadata_document(value) for value in documents):
            raise ValidationError(
                "INVALID_BUILD_DOCUMENT",
                "reserved project metadata cannot be compiled as source",
            )
        return documents

    @staticmethod
    def _require_program_documents(
        state: dict[str, JsonObject],
        documents: list[str],
    ) -> None:
        for document in documents:
            if is_project_metadata_document(document) or document not in state:
                raise NotFoundError(f"program document {document!r} not found")

    def delete(
        self,
        project: str,
        branch: str,
        name: str,
        *,
        expected_revision_id: str | None = None,
        author: str = "agent",
    ) -> dict[str, Any]:
        target_name = self._validate_name(name)
        base_revision_id, state = self.workspace._state_for_write(
            project,
            branch,
            expected_revision_id=expected_revision_id,
        )
        storage_document = self._storage_document(target_name)
        if storage_document not in state:
            raise NotFoundError(f"build target {target_name!r} not found")
        require_build_target_not_referenced(state, target_name)
        del state[storage_document]
        revision_id = self.workspace._commit(
            project,
            branch,
            state,
            message=f"delete build target {target_name}",
            author=author,
            operations=[
                ("delete_build_target", storage_document, {"name": target_name})
            ],
            expected_branch_heads={branch: base_revision_id},
            stale_error_code="STALE_BRANCH_HEAD",
        )
        return {
            "name": target_name,
            "branch": branch,
            "base_revision_id": base_revision_id,
            "revision_id": revision_id,
            "deleted": True,
        }

    def program_documents(
        self,
        project: str,
        *,
        branch: str = "main",
        revision_id: str | None = None,
    ) -> list[str]:
        revision = revision_id or self.workspace.branch_head(project, branch)
        self._require_project_revision(project, revision)
        return sorted(
            name
            for name in self.workspace._state_at_revision(revision)
            if not is_project_metadata_document(name)
        )
