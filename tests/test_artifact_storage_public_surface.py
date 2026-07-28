from __future__ import annotations

from weave_frontend.mcp_revert_guidance import weave_help


def test_artifact_storage_has_dedicated_help_topic() -> None:
    response = weave_help("storage")

    assert response["ok"] is True
    assert response["topic"] == "storage"
    assert response["help"]["tool"] == "artifact_storage_report"
    assert "WEAVE_ARTIFACT_MAX_BYTES" in response["help"]["quota"]
    assert "does not implement retention" in response["help"]["boundary"]


def test_public_application_manifest_contains_artifact_storage() -> None:
    from weave_jacquard.mcp_build import (
        PUBLIC_APPLICATION_MANIFEST,
        PUBLIC_TOOL_MANIFEST,
    )

    assert "artifact_storage_report" in PUBLIC_TOOL_MANIFEST["tool_names"]
    assert (
        PUBLIC_APPLICATION_MANIFEST["tool_count"]
        == len(PUBLIC_TOOL_MANIFEST["tool_names"])
    )
    assert (
        PUBLIC_APPLICATION_MANIFEST["tool_manifest_id"]
        == PUBLIC_TOOL_MANIFEST["tool_manifest_id"]
    )
