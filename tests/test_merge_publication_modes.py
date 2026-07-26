from __future__ import annotations

import pytest

from weave_frontend.errors import ValidationError
from weave_frontend.mcp_build import _publish_merge


def test_publication_rejects_single_and_all_target_validation_together() -> None:
    with pytest.raises(ValidationError) as raised:
        _publish_merge(
            "project",
            "target",
            "source",
            preview_id=None,
            validation_target="application",
            validate_affected_targets=True,
            allow_uncovered_documents=False,
            author="agent",
        )

    assert raised.value.code == "INVALID_MERGE_VALIDATION_MODE"


def test_publication_rejects_uncovered_override_without_all_target_gate() -> None:
    with pytest.raises(ValidationError) as raised:
        _publish_merge(
            "project",
            "target",
            "source",
            preview_id=None,
            validation_target=None,
            validate_affected_targets=False,
            allow_uncovered_documents=True,
            author="agent",
        )

    assert raised.value.code == "INVALID_MERGE_VALIDATION_MODE"
