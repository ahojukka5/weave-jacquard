from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from weave_frontend.errors import ValidationError
from weave_frontend.mcp_capabilities import PUBLIC_CAPABILITIES
from weave_frontend.mcp_revert_guidance import weave_help
from weave_frontend.runtime_identity import (
    RUNTIME_IDENTITY_FORMAT,
    RuntimeIdentityService,
)


class _Database:
    def __init__(self) -> None:
        self.path = Path("/secret/database")
        self.busy_timeout_ms = 25
        self.connection = sqlite3.connect(":memory:")
        self.connection.execute("PRAGMA foreign_keys = ON")


class _Workspace:
    def __init__(self) -> None:
        self.db = _Database()


class _Compiler:
    def _compiler_path(self) -> Path:
        return Path(sys.executable).resolve()


class _UnavailableCompiler:
    def _compiler_path(self) -> Path:
        raise ValidationError(
            "WEAVEC_NOT_EXECUTABLE",
            "weavec is not executable: /secret/compiler",
        )


class _Sandbox:
    executable = Path(sys.executable).resolve()
    prlimit = Path(sys.executable).resolve()

    @staticmethod
    def capabilities() -> dict[str, Any]:
        return {
            "format": "weave-sandbox-capabilities-v1",
            "backend": "fake",
            "platform": "test",
            "available": True,
            "version": "fake 1",
            "probe_error": None,
            "policy": {
                "network": "deny",
                "host_runtime_paths": ["/usr"],
            },
            "policy_hash": "c" * 64,
            "resource_limits": {"process_count": True},
        }


def _application_manifest(application_id: str = "a" * 64) -> dict[str, Any]:
    return {
        "format": "weave-jacquard-application-v2",
        "application_id": application_id,
        "tool_manifest_id": "b" * 64,
        "tool_count": 7,
        "capabilities": [{"name": "test", "module": "test", "depends_on": []}],
        "configuration_variables": ["WEAVE_DB_PATH", "WEAVEC_BIN"],
    }


def test_runtime_identity_binds_application_and_active_components() -> None:
    workspace = _Workspace()
    try:
        service = RuntimeIdentityService(
            workspace,
            _Compiler(),
            _Sandbox(),
            _application_manifest,
            environ={"WEAVEC_BIN": "/secret/compiler"},
        )

        report = service.report()

        assert report["format"] == RUNTIME_IDENTITY_FORMAT
        assert report["jacquard"]["application_id"] == "a" * 64
        assert report["jacquard"]["tool_manifest_id"] == "b" * 64
        assert report["jacquard"]["tool_count"] == 7
        assert report["jacquard"]["capability_count"] == 1
        assert report["database"] == {
            "schema_version": 3,
            "busy_timeout_ms": 25,
            "journal_mode": "memory",
            "foreign_keys": True,
            "location_id": RuntimeIdentityService._opaque_value_id(
                "database_path",
                str(workspace.db.path.resolve()),
            ),
        }
        assert report["compiler"]["available"] is True
        assert report["compiler"]["binary"]["sha256"]
        assert report["compiler"]["version"]
        assert report["sandbox"]["available"] is True
        assert report["configuration"] == {
            "variables": ["WEAVEC_BIN", "WEAVE_DB_PATH"],
            "configured_variables": ["WEAVEC_BIN"],
            "value_ids": {
                "WEAVEC_BIN": RuntimeIdentityService._opaque_value_id(
                    "WEAVEC_BIN",
                    "/secret/compiler",
                )
            },
            "values_redacted": True,
        }
        assert len(report["runtime_id"]) == 64
        assert report == service.report()
        encoded = json.dumps(report, sort_keys=True)
        assert "/secret/compiler" not in encoded
        assert "/secret/database" not in encoded
    finally:
        workspace.db.connection.close()


def test_runtime_identity_changes_with_application_identity() -> None:
    first_workspace = _Workspace()
    second_workspace = _Workspace()
    try:
        first = RuntimeIdentityService(
            first_workspace,
            _Compiler(),
            _Sandbox(),
            lambda: _application_manifest("a" * 64),
            environ={},
        ).report()
        second = RuntimeIdentityService(
            second_workspace,
            _Compiler(),
            _Sandbox(),
            lambda: _application_manifest("d" * 64),
            environ={},
        ).report()

        assert first["runtime_id"] != second["runtime_id"]
    finally:
        first_workspace.db.connection.close()
        second_workspace.db.connection.close()


def test_runtime_identity_changes_with_redacted_configuration_value() -> None:
    first_workspace = _Workspace()
    second_workspace = _Workspace()
    try:
        first = RuntimeIdentityService(
            first_workspace,
            _Compiler(),
            _Sandbox(),
            _application_manifest,
            environ={"WEAVEC_BIN": "/first/compiler"},
        ).report()
        second = RuntimeIdentityService(
            second_workspace,
            _Compiler(),
            _Sandbox(),
            _application_manifest,
            environ={"WEAVEC_BIN": "/second/compiler"},
        ).report()

        assert first["configuration"]["value_ids"] != second["configuration"]["value_ids"]
        assert first["runtime_id"] != second["runtime_id"]
    finally:
        first_workspace.db.connection.close()
        second_workspace.db.connection.close()


def test_runtime_identity_redacts_unavailable_compiler_path() -> None:
    workspace = _Workspace()
    try:
        report = RuntimeIdentityService(
            workspace,
            _UnavailableCompiler(),
            _Sandbox(),
            _application_manifest,
            environ={},
        ).report()

        assert report["compiler"]["available"] is False
        assert report["compiler"]["error"]["code"] == "WEAVEC_NOT_EXECUTABLE"
        assert "/secret/compiler" not in json.dumps(report, sort_keys=True)
    finally:
        workspace.db.connection.close()


def test_runtime_identity_capability_is_last_and_explicit() -> None:
    capability = PUBLIC_CAPABILITIES[-1]

    assert capability.name == "runtime_identity"
    assert capability.module == "weave_frontend.mcp_runtime_identity"
    assert capability.depends_on == (
        "revision_reads",
        "database_backup",
        "artifact_storage",
    )


def test_runtime_identity_has_dedicated_help_topic() -> None:
    response = weave_help("runtime")

    assert response["ok"] is True
    assert response["topic"] == "runtime"
    assert response["help"]["tool"] == "runtime_identity"
    assert "not proof" in response["help"]["boundary"]


def test_public_application_manifest_contains_runtime_identity() -> None:
    from weave_jacquard.mcp_build import (
        PUBLIC_APPLICATION_MANIFEST,
        PUBLIC_TOOL_MANIFEST,
    )

    assert "runtime_identity" in PUBLIC_TOOL_MANIFEST["tool_names"]
    assert PUBLIC_APPLICATION_MANIFEST["tool_count"] == len(PUBLIC_TOOL_MANIFEST["tool_names"])
    assert (
        PUBLIC_APPLICATION_MANIFEST["tool_manifest_id"] == PUBLIC_TOOL_MANIFEST["tool_manifest_id"]
    )
