from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from weave_frontend.application import JacquardApp
from weave_frontend.runtime import RuntimeConfig, RuntimeServices, runtime_services


def _runtime(tmp_path: Path, name: str) -> RuntimeServices:
    root = tmp_path / name
    root.mkdir()
    return RuntimeServices(
        RuntimeConfig.from_environ(
            {
                "WEAVE_DB_PATH": str(root / "jacquard.db"),
                "WEAVE_BUILD_ROOT": str(root / "builds"),
                "WEAVE_DATABASE_BACKUP_ROOT": str(root / "backups"),
                "WEAVE_MERGE_ATTESTATION_ROOT": str(root / "attestations"),
                "WEAVE_MERGE_BUILD_ROOT": str(root / "merge-builds"),
                "WEAVE_MERGE_TEST_RUN_ROOT": str(root / "merge-tests"),
                "WEAVE_TEST_BATCH_ROOT": str(root / "test-batches"),
                "WEAVE_TEST_RUN_ROOT": str(root / "test-runs"),
            }
        )
    )


def _structured(result: Any) -> dict[str, Any]:
    if isinstance(result, Mapping):
        return dict(result)

    payload = getattr(result, "structuredContent", None)
    if payload is None:
        payload = getattr(result, "structured_content", None)
    if isinstance(payload, Mapping):
        return dict(payload)

    if isinstance(result, Sequence) and not isinstance(
        result,
        (str, bytes, bytearray),
    ):
        if len(result) == 2 and isinstance(result[1], Mapping):
            return dict(result[1])
        content: Any = result
    else:
        content = getattr(result, "content", None)

    if isinstance(content, Sequence) and not isinstance(
        content,
        (str, bytes, bytearray),
    ):
        for block in content:
            text = getattr(block, "text", None)
            if not isinstance(text, str):
                continue
            decoded = json.loads(text)
            if isinstance(decoded, Mapping):
                return dict(decoded)

    raise AssertionError("tool result has no structured mapping payload")


def test_two_complete_applications_coexist_and_close_independently(
    tmp_path: Path,
) -> None:
    process_runtime = runtime_services()
    left_runtime = _runtime(tmp_path, "left")
    right_runtime = _runtime(tmp_path, "right")
    left_server = FastMCP("left-jacquard")
    right_server = FastMCP("right-jacquard")

    left_app = JacquardApp.compose(left_server, runtime=left_runtime)
    right_app = JacquardApp.compose(right_server, runtime=right_runtime)

    assert left_app.application_manifest == right_app.application_manifest
    assert left_app.tool_manifest == right_app.tool_manifest
    assert left_runtime.service_manifest(include_state=False) == (
        right_runtime.service_manifest(include_state=False)
    )
    assert left_runtime.config.database_path != right_runtime.config.database_path
    assert left_runtime.config.build_root != right_runtime.config.build_root
    assert left_runtime.config.test_run_root != right_runtime.config.test_run_root
    assert left_runtime.config.database_backup_root != (right_runtime.config.database_backup_root)

    async def exercise() -> None:
        left_initialize, right_initialize = await asyncio.gather(
            left_server.call_tool(
                "project_initialize",
                {"project": "left-only", "author": "left"},
            ),
            right_server.call_tool(
                "project_initialize",
                {"project": "right-only", "author": "right"},
            ),
        )
        assert _structured(left_initialize)["ok"] is True
        assert _structured(right_initialize)["ok"] is True

        left_own, right_own, left_cross, right_cross = await asyncio.gather(
            left_server.call_tool("branch_list", {"project": "left-only"}),
            right_server.call_tool("branch_list", {"project": "right-only"}),
            left_server.call_tool("branch_list", {"project": "right-only"}),
            right_server.call_tool("branch_list", {"project": "left-only"}),
        )
        left_own_payload = _structured(left_own)
        right_own_payload = _structured(right_own)
        left_cross_payload = _structured(left_cross)
        right_cross_payload = _structured(right_cross)
        assert left_own_payload["ok"] is True
        assert right_own_payload["ok"] is True
        assert [branch["name"] for branch in left_own_payload["result"]] == ["main"]
        assert [branch["name"] for branch in right_own_payload["result"]] == ["main"]
        assert left_cross_payload == {"ok": True, "result": []}
        assert right_cross_payload == {"ok": True, "result": []}

        left_runtime.close()
        assert left_runtime.closed is True
        assert right_runtime.closed is False

        right_after_left_close = await right_server.call_tool(
            "branch_list",
            {"project": "right-only"},
        )
        right_after_close_payload = _structured(right_after_left_close)
        assert right_after_close_payload["ok"] is True
        assert [branch["name"] for branch in right_after_close_payload["result"]] == ["main"]

    try:
        asyncio.run(exercise())
    finally:
        left_runtime.close()
        right_runtime.close()

    assert right_runtime.closed is True
    assert runtime_services() is process_runtime
