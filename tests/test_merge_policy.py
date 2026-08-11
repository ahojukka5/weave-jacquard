from __future__ import annotations

import pytest

from weave_frontend.errors import ValidationError
from weave_frontend.merges import MERGE_POLICY_FORMAT, MergePolicyRegistry


def test_default_policy_preserves_legacy_merge_compatibility(sexpr_workspace) -> None:
    registry = MergePolicyRegistry(sexpr_workspace)

    policy = registry.get("sexpr-demo")

    assert policy["format"] == MERGE_POLICY_FORMAT
    assert policy["configured"] is False
    assert policy["require_preflight"] is False
    assert policy["require_affected_validation"] is False
    assert policy["allow_uncovered_documents"] is True
    assert policy["max_affected_targets"] == 64
    assert policy["policy_revision_id"] is None
    assert len(policy["policy_hash"]) == 64


def test_policy_is_revisioned_and_historically_reproducible(sexpr_workspace) -> None:
    registry = MergePolicyRegistry(sexpr_workspace)
    initial_revision = sexpr_workspace.branch_head("sexpr-demo", "main")

    configured = registry.set(
        "sexpr-demo",
        require_preflight=True,
        require_affected_validation=True,
        allow_uncovered_documents=False,
        max_affected_targets=7,
    )

    assert configured["configured"] is True
    assert configured["policy_revision_id"] == configured["revision_id"]
    assert configured["revision_id"] != initial_revision
    assert registry.get("sexpr-demo") == configured

    historical = registry.get("sexpr-demo", revision_id=initial_revision)
    assert historical["configured"] is False
    assert historical["revision_id"] == initial_revision

    row = sexpr_workspace.db.connection.execute(
        """SELECT operation_kind, payload_json
           FROM operations WHERE revision_id = ?""",
        (configured["revision_id"],),
    ).fetchone()
    assert row is not None
    assert row["operation_kind"] == "set_merge_policy"
    assert configured["policy_hash"] in row["payload_json"]


def test_identical_policy_reuses_content_document_but_publishes_new_revision(
    sexpr_workspace,
) -> None:
    registry = MergePolicyRegistry(sexpr_workspace)

    first = registry.set("sexpr-demo", max_affected_targets=9)
    second = registry.set("sexpr-demo", max_affected_targets=9)

    assert second["revision_id"] != first["revision_id"]
    assert second["document_id"] == first["document_id"]
    assert second["policy_hash"] == first["policy_hash"]
    count = sexpr_workspace.db.connection.execute(
        "SELECT COUNT(*) AS count FROM documents WHERE title = ?",
        ("Jacquard merge policy",),
    ).fetchone()
    assert count is not None
    assert count["count"] == 1


def test_target_first_parent_policy_overrides_weaker_source_policy(
    sexpr_workspace,
) -> None:
    registry = MergePolicyRegistry(sexpr_workspace)
    strict = registry.set(
        "sexpr-demo",
        "main",
        require_preflight=True,
        require_affected_validation=True,
        allow_uncovered_documents=False,
        max_affected_targets=4,
    )
    sexpr_workspace.create_branch("sexpr-demo", "protected", from_branch="main")
    sexpr_workspace.create_branch("sexpr-demo", "incoming", from_branch="main")

    inherited = registry.get("sexpr-demo", "protected")
    assert inherited["policy_hash"] == strict["policy_hash"]
    assert inherited["policy_revision_id"] == strict["policy_revision_id"]

    weak = registry.set(
        "sexpr-demo",
        "incoming",
        require_preflight=False,
        require_affected_validation=False,
        allow_uncovered_documents=True,
        max_affected_targets=64,
    )
    compared = registry.compare("sexpr-demo", "protected", "incoming")

    assert compared["target"]["policy_hash"] == strict["policy_hash"]
    assert compared["source"]["policy_hash"] == weak["policy_hash"]
    assert compared["source_policy_ignored"] is True
    assert compared["target"]["allow_uncovered_documents"] is False
    assert compared["source"]["allow_uncovered_documents"] is True

    loosened = registry.set(
        "sexpr-demo",
        "protected",
        require_preflight=False,
        require_affected_validation=False,
        allow_uncovered_documents=True,
        max_affected_targets=12,
    )
    compared_after = registry.compare("sexpr-demo", "protected", "incoming")
    assert compared_after["target"]["policy_hash"] == loosened["policy_hash"]
    assert compared_after["target"]["policy_revision_id"] == loosened["revision_id"]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"require_preflight": "yes"}, "require_preflight must be a boolean"),
        (
            {"require_affected_validation": 1},
            "require_affected_validation must be a boolean",
        ),
        (
            {"allow_uncovered_documents": None},
            "allow_uncovered_documents must be a boolean",
        ),
        ({"max_affected_targets": 0}, "max_affected_targets must be between"),
        ({"max_affected_targets": 65}, "max_affected_targets must be between"),
        (
            {"require_preflight": True, "require_affected_validation": False},
            "require_preflight requires require_affected_validation",
        ),
    ],
)
def test_policy_rejects_invalid_values(sexpr_workspace, kwargs, message) -> None:
    registry = MergePolicyRegistry(sexpr_workspace)

    with pytest.raises(ValidationError) as raised:
        registry.set("sexpr-demo", **kwargs)

    assert raised.value.code == "INVALID_MERGE_POLICY"
    assert message in str(raised.value)
