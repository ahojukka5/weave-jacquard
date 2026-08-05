"""Production MCP registration for revisioned merge admission policies."""

from __future__ import annotations

from typing import Any

from .errors import ValidationError
from .mcp_build import _publish_merge, merge_previews, merge_validation_sets
from .mcp_preflight import merge_policies, merge_preflights
from .mcp_server import _result, mcp

mcp.remove_tool("branch_merge")


@mcp.tool()
def merge_policy_get(
    project: str,
    branch: str = "main",
    revision_id: str | None = None,
) -> dict[str, object]:
    """Read the effective first-parent merge policy for a branch or revision."""

    return _result(
        lambda: merge_policies().get(
            project,
            branch,
            revision_id=revision_id,
        )
    )


@mcp.tool()
def merge_policy_set(
    project: str,
    branch: str = "main",
    require_preflight: bool = True,
    require_affected_validation: bool = True,
    allow_uncovered_documents: bool = False,
    max_affected_targets: int = 64,
    author: str = "policy-agent",
) -> dict[str, object]:
    """Publish one immutable target-branch merge admission policy revision."""

    return _result(
        lambda: merge_policies().set(
            project,
            branch,
            require_preflight=require_preflight,
            require_affected_validation=require_affected_validation,
            allow_uncovered_documents=allow_uncovered_documents,
            max_affected_targets=max_affected_targets,
            author=author,
        )
    )


def _validate_modes(
    *,
    validation_target: str | None,
    validate_affected_targets: bool,
    allow_uncovered_documents: bool,
    preflight_id: str | None,
) -> None:
    if validation_target is not None and validate_affected_targets:
        raise ValidationError(
            "INVALID_MERGE_VALIDATION_MODE",
            "choose validation_target or validate_affected_targets, not both",
        )
    if allow_uncovered_documents and not validate_affected_targets:
        raise ValidationError(
            "INVALID_MERGE_VALIDATION_MODE",
            "allow_uncovered_documents requires validate_affected_targets",
        )
    if preflight_id is not None and (not isinstance(preflight_id, str) or not preflight_id):
        raise ValidationError(
            "INVALID_MERGE_PREFLIGHT_ID",
            "preflight_id must be a non-empty string",
        )
    if preflight_id is not None and (
        validation_target is not None or not validate_affected_targets
    ):
        raise ValidationError(
            "INVALID_MERGE_VALIDATION_MODE",
            "preflight replay requires validate_affected_targets and no validation_target",
        )


def _policy_metadata(
    policy_context: dict[str, Any],
    *,
    preflight_id: str | None,
) -> dict[str, Any]:
    return {
        "merge_policy_enforced": bool(policy_context["target"]["configured"]),
        "target_merge_policy": policy_context["target"],
        "source_merge_policy": policy_context["source"],
        "source_policy_ignored": policy_context["source_policy_ignored"],
        "preflight_enforced": preflight_id is not None,
        "preflight_id": preflight_id,
    }


def _publish_all_affected(
    project: str,
    target_branch: str,
    source_branch: str,
    *,
    preview_id: str | None,
    allow_uncovered_documents: bool,
    max_target_validations: int,
    author: str,
    policy_context: dict[str, Any],
    preflight_id: str | None,
) -> dict[str, Any]:
    validation_set = merge_validation_sets().validate(
        project,
        target_branch,
        source_branch,
        preview_id=preview_id,
        allow_uncovered_documents=allow_uncovered_documents,
        max_target_validations=max_target_validations,
    )
    merge_validation_sets().require_ready(validation_set)
    result = merge_previews().merge(
        project,
        target_branch,
        source_branch,
        preview_id=str(validation_set["preview_id"]),
        author=author,
    )
    result.update(
        {
            "validation_target": None,
            "validation_enforced": False,
            "merge_validation": None,
            "affected_validation_enforced": True,
            "allow_uncovered_documents": allow_uncovered_documents,
            "merge_validation_set": validation_set,
            **_policy_metadata(policy_context, preflight_id=preflight_id),
        }
    )
    return result


def _publish_merge_with_policy(
    project: str,
    target_branch: str,
    source_branch: str,
    *,
    preview_id: str | None,
    validation_target: str | None,
    validate_affected_targets: bool,
    allow_uncovered_documents: bool,
    preflight_id: str | None,
    author: str,
) -> dict[str, Any]:
    _validate_modes(
        validation_target=validation_target,
        validate_affected_targets=validate_affected_targets,
        allow_uncovered_documents=allow_uncovered_documents,
        preflight_id=preflight_id,
    )
    policy_context = merge_policies().compare(
        project,
        target_branch,
        source_branch,
    )
    target_policy = policy_context["target"]

    if allow_uncovered_documents and target_policy["allow_uncovered_documents"] is not True:
        raise ValidationError(
            "MERGE_POLICY_VIOLATION",
            "target merge policy forbids uncovered-document overrides",
        )
    if target_policy["require_affected_validation"] is True and not validate_affected_targets:
        raise ValidationError(
            "MERGE_POLICY_AFFECTED_VALIDATION_REQUIRED",
            "target merge policy requires all affected surviving targets to validate",
        )
    if target_policy["require_preflight"] is True and preflight_id is None:
        raise ValidationError(
            "MERGE_POLICY_PREFLIGHT_REQUIRED",
            "target merge policy requires a replayed branch_merge_preflight result",
        )

    if preflight_id is not None:
        preflight = merge_preflights().run(
            project,
            target_branch,
            source_branch,
            preview_id=preview_id,
            allow_uncovered_documents=allow_uncovered_documents,
        )
        if preflight_id != preflight["preflight_id"]:
            raise ValidationError(
                "STALE_MERGE_PREFLIGHT",
                "merge preflight evidence no longer matches current branches or policy",
            )
        merge_validation_sets().require_ready(preflight["validation_set"])
        result = merge_previews().merge(
            project,
            target_branch,
            source_branch,
            preview_id=str(preflight["preview_id"]),
            author=author,
        )
        result.update(
            {
                "validation_target": None,
                "validation_enforced": False,
                "merge_validation": None,
                "affected_validation_enforced": True,
                "allow_uncovered_documents": allow_uncovered_documents,
                "merge_validation_set": preflight["validation_set"],
                **_policy_metadata(policy_context, preflight_id=preflight_id),
            }
        )
        return result

    if validate_affected_targets and target_policy["configured"] is True:
        return _publish_all_affected(
            project,
            target_branch,
            source_branch,
            preview_id=preview_id,
            allow_uncovered_documents=allow_uncovered_documents,
            max_target_validations=int(target_policy["max_affected_targets"]),
            author=author,
            policy_context=policy_context,
            preflight_id=None,
        )

    result = _publish_merge(
        project,
        target_branch,
        source_branch,
        preview_id=preview_id,
        validation_target=validation_target,
        validate_affected_targets=validate_affected_targets,
        allow_uncovered_documents=allow_uncovered_documents,
        author=author,
    )
    result.update(_policy_metadata(policy_context, preflight_id=None))
    return result


@mcp.tool()
def branch_merge(
    project: str,
    target_branch: str,
    source_branch: str,
    preview_id: str | None = None,
    validation_target: str | None = None,
    validate_affected_targets: bool = False,
    allow_uncovered_documents: bool = False,
    preflight_id: str | None = None,
    author: str = "merge-agent",
) -> dict[str, object]:
    """Publish a merge under the target branch's revisioned admission policy."""

    return _result(
        lambda: _publish_merge_with_policy(
            project,
            target_branch,
            source_branch,
            preview_id=preview_id,
            validation_target=validation_target,
            validate_affected_targets=validate_affected_targets,
            allow_uncovered_documents=allow_uncovered_documents,
            preflight_id=preflight_id,
            author=author,
        )
    )
