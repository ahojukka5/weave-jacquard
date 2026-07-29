from __future__ import annotations

import pytest

import weave_frontend.branch_activity as branch_activity_module
from weave_frontend.branch_activity import BranchActivityService
from weave_frontend.errors import ValidationError


def test_activity_summary_accepts_exact_limit_and_rejects_plus_one(
    monkeypatch: pytest.MonkeyPatch,
    sexpr_workspace,
) -> None:
    monkeypatch.setattr(branch_activity_module, "MAX_BRANCH_ACTIVITY_REVISIONS", 2)
    created = sexpr_workspace.create_program(
        "sexpr-demo",
        "main",
        "main.weave",
        program_name="bounded-activity",
    )
    service = BranchActivityService(sexpr_workspace)

    exact = service.summary("sexpr-demo")

    assert exact["revision_count"] == 2
    assert exact["complete"] is True
    assert exact["truncated"] is False
    assert exact["limits"] == {"maximum_first_parent_revisions": 2}

    sexpr_workspace.create_form(
        "sexpr-demo",
        "main",
        "main.weave",
        created["node_id"],
        "later",
    )

    with pytest.raises(ValidationError) as captured:
        service.summary("sexpr-demo")

    assert captured.value.code == "BRANCH_ACTIVITY_REVISION_LIMIT_EXCEEDED"
