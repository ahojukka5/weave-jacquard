"""Build-target registry aware of every reserved project metadata class."""

from __future__ import annotations

from .concurrent_build_targets import BuildTargetRegistry as _BaseBuildTargetRegistry
from .errors import NotFoundError, ValidationError
from .project_metadata import is_project_metadata_document
from .sexpr import JsonObject


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
