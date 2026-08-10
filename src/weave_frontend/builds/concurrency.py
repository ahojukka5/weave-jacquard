"""Race-safe build-target metadata mutations."""

from __future__ import annotations

from typing import Any

from ..build_targets import BuildTargetRegistry as _BaseBuildTargetRegistry
from ..compiler import normalize_evidence_profile
from ..errors import NotFoundError, ValidationError
from ..revision_limits import MAX_BUILD_DOCUMENTS
from ..sexpr import validate_tree


class BuildTargetRegistry(_BaseBuildTargetRegistry):
    """Build-target registry whose writes compare-and-set one captured branch head."""

    @classmethod
    def _validate_document_set(
        cls,
        document: str,
        additional_documents: list[str] | None,
    ) -> list[str]:
        documents = super()._validate_document_set(document, additional_documents)
        if len(documents) > MAX_BUILD_DOCUMENTS:
            raise ValidationError(
                "BUILD_DOCUMENT_LIMIT_EXCEEDED",
                f"one build target may reference at most {MAX_BUILD_DOCUMENTS} documents",
            )
        return documents

    def set(
        self,
        project: str,
        branch: str,
        name: str,
        document: str,
        *,
        additional_documents: list[str] | None = None,
        compiler_target: str | None = None,
        evidence_profile: str | None = None,
        expected_revision_id: str | None = None,
        author: str = "agent",
    ) -> dict[str, Any]:
        target_name = self._validate_name(name)
        documents = self._validate_document_set(document, additional_documents)
        effective_target = self._normalize_compiler_target(compiler_target)
        effective_profile = normalize_evidence_profile(evidence_profile)
        base_revision_id, state = self.workspace._state_for_write(
            project,
            branch,
            expected_revision_id=expected_revision_id,
        )
        self._require_program_documents(state, documents)
        storage_document = self._storage_document(target_name)
        root = self._build_tree(
            document,
            documents[1:],
            effective_target,
            effective_profile,
            existing=state.get(storage_document),
        )
        validate_tree(root)
        state[storage_document] = root
        config = self._config(
            target_name,
            document,
            documents[1:],
            effective_target,
            effective_profile,
        )
        revision = self.workspace._commit(
            project,
            branch,
            state,
            message=f"set build target {target_name}",
            author=author,
            operations=[("set_build_target", storage_document, config)],
            expected_branch_heads={branch: base_revision_id},
            stale_error_code="STALE_BRANCH_HEAD",
        )
        return {
            **config,
            "branch": branch,
            "base_revision_id": base_revision_id,
            "revision_id": revision,
            "storage_document": storage_document,
            "root_node_id": root["id"],
        }

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
        del state[storage_document]
        revision = self.workspace._commit(
            project,
            branch,
            state,
            message=f"delete build target {target_name}",
            author=author,
            operations=[("delete_build_target", storage_document, {"name": target_name})],
            expected_branch_heads={branch: base_revision_id},
            stale_error_code="STALE_BRANCH_HEAD",
        )
        return {
            "name": target_name,
            "branch": branch,
            "base_revision_id": base_revision_id,
            "revision_id": revision,
            "deleted": True,
        }
