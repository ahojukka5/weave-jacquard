from __future__ import annotations

from weave_frontend.mcp_database_backup import DATABASE_BACKUP_ROOT_ENV
from weave_frontend.mcp_revert_guidance import weave_help


def test_database_backup_has_dedicated_help_topic() -> None:
    response = weave_help("backup")

    assert response["ok"] is True
    assert response["topic"] == "backup"
    assert response["help"]["tools"] == [
        "database_backup_create",
        "database_backup_get",
    ]
    assert "aggregate retained-artifact quota" in response["help"]["quota"]
    assert "offline" in response["help"]["restore"]


def test_public_application_manifest_contains_backup_contract() -> None:
    from weave_jacquard.mcp_build import (
        PUBLIC_APPLICATION_MANIFEST,
        PUBLIC_TOOL_MANIFEST,
    )

    tool_names = PUBLIC_TOOL_MANIFEST["tool_names"]
    assert "database_backup_create" in tool_names
    assert "database_backup_get" in tool_names
    assert "database_restore" not in tool_names
    assert DATABASE_BACKUP_ROOT_ENV in PUBLIC_APPLICATION_MANIFEST["configuration_variables"]
    assert PUBLIC_APPLICATION_MANIFEST["tool_count"] == len(PUBLIC_TOOL_MANIFEST["tool_names"])
