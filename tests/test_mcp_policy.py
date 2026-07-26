from __future__ import annotations

from typing import Any

import pytest

from weave_frontend.errors import ValidationError
from weave_frontend import mcp_policy


class _Policies:
    def __init__(
        self,
        *,
        configured: bool = True,
        require_preflight: bool = True,
        require_affected: bool = True,
        allow_uncovered: bool = False,
        maximum: int = 3,
    ) -> None:
        self.target = {
            "configured": configured,
            "policy_hash": "target-policy",
            "require_preflight": require_preflight,
            "require_affected_validation": require_affected,
            "allow_uncovered_documents": allow_uncovered,
            "max_affected_targets": maximum,
        }
        self.source = {
            "configured": True,
            "policy_hash": "source-policy",
            "require_preflight": False,
            "require_affected_validation": False,
            "allow_uncovered_documents": True,
            "max_affected_targets": 64,
        }
        self.calls: list[tuple[str, str, str]] = []

    def compare(self, project: str, target: str, source: str) -> dict[str, Any]:
        self.calls.append((project, target, source))
        return {
            "target": dict(self.target),
            "source": dict(self.source),
            "source_policy_ignored": True,
        }


class _Preflights:
    def __init__(self, *, identity: str = "preflight", ready: bool = True) -> None:
        self.identity = identity
        self.ready = ready
        self.calls: list[dict[str, Any]] = []

    def run(
        self,
        project: str,
        target: str,
        source: str,
        *,
        preview_id: str | None,
        allow_uncovered_documents: bool,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "project": project,
                "target": target,
                "source": source,
                "preview_id": preview_id,
                "allow_uncovered_documents": allow_uncovered_documents,
            }
        )
        return {
            "preflight_id": self.identity,
            "preview_id": "reviewed-preview",
            "validation_set": {
                "preview_id": "reviewed-preview",
                "ready_for_publication": self.ready,
                "coverage_passed": self.ready,
                "failed_targets": [] if self.ready else ["application"],
                "unavailable_targets": [],
            },
        }


class _ValidationSets:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.required: list[dict[str, Any]] = []

    def validate(self, project: str, target: str, source: str, **kwargs: Any):
        self.calls.append(
            {
                "project": project,
                "target": target,
                "source": source,
                **kwargs,
            }
        )
        return {
            "preview_id": "validated-preview",
            "ready_for_publication": True,
            "coverage_passed": True,
            "failed_targets": [],
            "unavailable_targets": [],
        }

    def require_ready(self, result: dict[str, Any]) -> None:
        self.required.append(result)
        if result.get("ready_for_publication") is not True:
            raise ValidationError("MERGE_VALIDATION_FAILED", "not ready")


class _Previews:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def merge(
        self,
        project: str,
        target: str,
        source: str,
        *,
        preview_id: str | None,
        author: str,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "project": project,
                "target": target,
                "source": source,
                "preview_id": preview_id,
                "author": author,
            }
        )
        return {
            "revision_id": "merged-revision",
            "target_branch": target,
            "source_branch": source,
        }


def _install(
    monkeypatch,
    *,
    policies: _Policies,
    preflights: _Preflights | None = None,
    validations: _ValidationSets | None = None,
    previews: _Previews | None = None,
):
    preflights = preflights or _Preflights()
    validations = validations or _ValidationSets()
    previews = previews or _Previews()
    legacy_calls: list[dict[str, Any]] = []

    monkeypatch.setattr(mcp_policy, "merge_policies", lambda: policies)
    monkeypatch.setattr(mcp_policy, "merge_preflights", lambda: preflights)
    monkeypatch.setattr(mcp_policy, "merge_validation_sets", lambda: validations)
    monkeypatch.setattr(mcp_policy, "merge_previews", lambda: previews)

    def legacy(*args: Any, **kwargs: Any) -> dict[str, Any]:
        legacy_calls.append({"args": args, "kwargs": kwargs})
        return {"revision_id": "legacy-merge"}

    monkeypatch.setattr(mcp_policy, "_publish_merge", legacy)
    return preflights, validations, previews, legacy_calls


def _publish(**overrides: Any) -> dict[str, Any]:
    values = {
        "project": "demo",
        "target_branch": "protected",
        "source_branch": "incoming",
        "preview_id": "reviewed-preview",
        "validation_target": None,
        "validate_affected_targets": False,
        "allow_uncovered_documents": False,
        "preflight_id": None,
        "author": "merge-agent",
    }
    values.update(overrides)
    return mcp_policy._publish_merge_with_policy(**values)


def test_strict_policy_requires_preflight_before_publication(monkeypatch) -> None:
    policies = _Policies()
    _, _, previews, legacy = _install(monkeypatch, policies=policies)

    with pytest.raises(ValidationError) as raised:
        _publish(validate_affected_targets=True)

    assert raised.value.code == "MERGE_POLICY_PREFLIGHT_REQUIRED"
    assert previews.calls == []
    assert legacy == []


def test_strict_policy_requires_all_affected_validation(monkeypatch) -> None:
    policies = _Policies(require_preflight=False, require_affected=True)
    _install(monkeypatch, policies=policies)

    with pytest.raises(ValidationError) as raised:
        _publish(validation_target="application")

    assert raised.value.code == "MERGE_POLICY_AFFECTED_VALIDATION_REQUIRED"


def test_exact_preflight_replay_publishes_once_with_policy_evidence(monkeypatch) -> None:
    policies = _Policies(maximum=2)
    preflights, validations, previews, legacy = _install(
        monkeypatch,
        policies=policies,
    )

    result = _publish(
        validate_affected_targets=True,
        preflight_id="preflight",
    )

    assert len(preflights.calls) == 1
    assert validations.calls == []
    assert len(validations.required) == 1
    assert previews.calls == [
        {
            "project": "demo",
            "target": "protected",
            "source": "incoming",
            "preview_id": "reviewed-preview",
            "author": "merge-agent",
        }
    ]
    assert legacy == []
    assert result["preflight_enforced"] is True
    assert result["preflight_id"] == "preflight"
    assert result["affected_validation_enforced"] is True
    assert result["merge_policy_enforced"] is True
    assert result["source_policy_ignored"] is True
    assert result["target_merge_policy"]["policy_hash"] == "target-policy"


def test_mismatched_preflight_identity_is_rejected_without_merge(monkeypatch) -> None:
    policies = _Policies()
    preflights = _Preflights(identity="new-preflight")
    _, _, previews, legacy = _install(
        monkeypatch,
        policies=policies,
        preflights=preflights,
    )

    with pytest.raises(ValidationError) as raised:
        _publish(
            validate_affected_targets=True,
            preflight_id="old-preflight",
        )

    assert raised.value.code == "STALE_MERGE_PREFLIGHT"
    assert previews.calls == []
    assert legacy == []


def test_configured_non_preflight_policy_applies_lower_fanout_limit(monkeypatch) -> None:
    policies = _Policies(
        require_preflight=False,
        require_affected=True,
        maximum=2,
    )
    _, validations, previews, legacy = _install(monkeypatch, policies=policies)

    result = _publish(validate_affected_targets=True)

    assert validations.calls[0]["max_target_validations"] == 2
    assert previews.calls[0]["preview_id"] == "validated-preview"
    assert legacy == []
    assert result["merge_policy_enforced"] is True
    assert result["preflight_enforced"] is False


def test_policy_forbids_uncovered_override_before_validation(monkeypatch) -> None:
    policies = _Policies(allow_uncovered=False)
    _, validations, previews, legacy = _install(monkeypatch, policies=policies)

    with pytest.raises(ValidationError) as raised:
        _publish(
            validate_affected_targets=True,
            allow_uncovered_documents=True,
            preflight_id="preflight",
        )

    assert raised.value.code == "MERGE_POLICY_VIOLATION"
    assert validations.calls == []
    assert previews.calls == []
    assert legacy == []


def test_unconfigured_policy_preserves_legacy_publication(monkeypatch) -> None:
    policies = _Policies(
        configured=False,
        require_preflight=False,
        require_affected=False,
        allow_uncovered=True,
    )
    _, _, previews, legacy = _install(monkeypatch, policies=policies)

    result = _publish()

    assert previews.calls == []
    assert len(legacy) == 1
    assert result["revision_id"] == "legacy-merge"
    assert result["merge_policy_enforced"] is False
    assert result["preflight_enforced"] is False


@pytest.mark.parametrize(
    "preflight_id",
    ["", 1],
)
def test_invalid_preflight_ids_are_rejected(monkeypatch, preflight_id) -> None:
    policies = _Policies()
    _install(monkeypatch, policies=policies)

    with pytest.raises(ValidationError) as raised:
        _publish(
            validate_affected_targets=True,
            preflight_id=preflight_id,
        )

    assert raised.value.code == "INVALID_MERGE_PREFLIGHT_ID"
