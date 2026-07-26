"""Race-safe atomic merge-policy publication."""

from __future__ import annotations

from typing import Any

from .merge_policy import (
    MERGE_POLICY_FORMAT,
    MERGE_POLICY_OPERATION,
    MERGE_POLICY_TITLE,
    MergePolicyRegistry as _BaseMergePolicyRegistry,
)
from .merge_validation_set import MAX_AFFECTED_TARGET_VALIDATIONS


class MergePolicyRegistry(_BaseMergePolicyRegistry):
    """Merge policies whose document and revision publish atomically."""

    def set(
        self,
        project: str,
        branch: str = "main",
        *,
        require_preflight: bool = True,
        require_affected_validation: bool = True,
        allow_uncovered_documents: bool = False,
        max_affected_targets: int = MAX_AFFECTED_TARGET_VALIDATIONS,
        expected_revision_id: str | None = None,
        author: str = "policy-agent",
    ) -> dict[str, Any]:
        policy = self._normalize(
            require_preflight=require_preflight,
            require_affected_validation=require_affected_validation,
            allow_uncovered_documents=allow_uncovered_documents,
            max_affected_targets=max_affected_targets,
        )
        body = self.workspace.db.canonical_json(policy)
        policy_hash = self.workspace.db.hash_value(policy)
        base_revision_id, state = self.workspace._state_for_write(
            project,
            branch,
            expected_revision_id=expected_revision_id,
        )
        revision, document_id = self.workspace._commit_content_document(
            project,
            branch,
            base_revision_id,
            state,
            scope_kind="project",
            scope_name=project,
            title=MERGE_POLICY_TITLE,
            body=body,
            message="set merge policy",
            author=author,
            operation_kind=MERGE_POLICY_OPERATION,
            operation_target=project,
            operation_payload={
                "format": MERGE_POLICY_FORMAT,
                "policy_hash": policy_hash,
            },
        )
        result = self._result(
            policy,
            configured=True,
            project=project,
            branch=branch,
            revision_id=revision,
            policy_revision_id=revision,
            document_id=document_id,
        )
        result["base_revision_id"] = base_revision_id
        return result
