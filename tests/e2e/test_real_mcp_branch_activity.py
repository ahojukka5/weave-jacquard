from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[2]


def _attribute(value: Any, snake: str, camel: str) -> Any:
    result = getattr(value, snake, None)
    return result if result is not None else getattr(value, camel, None)


def _payload(response: Any) -> dict[str, Any]:
    structured = _attribute(response, "structured_content", "structuredContent")
    if isinstance(structured, dict):
        return structured
    for block in getattr(response, "content", []):
        text = getattr(block, "text", None)
        if not isinstance(text, str):
            continue
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise AssertionError(f"tool result did not contain a JSON object: {response!r}")


async def _call(session: ClientSession, name: str, **arguments: Any) -> Any:
    response = await session.call_tool(name, arguments=arguments)
    payload = _payload(response)
    assert _attribute(response, "is_error", "isError") is not True, payload
    assert payload.get("ok") is True, payload
    return payload.get("result")


def _operations(root_id: str) -> list[dict[str, Any]]:
    return [
        {"op": "create_form", "parent": root_id, "head": "entry", "as": "entry"},
        {
            "op": "add_atom",
            "parent": "@entry",
            "kind": "symbol",
            "value": "main",
        },
        {"op": "create_form", "parent": "@entry", "head": "params"},
        {"op": "create_form", "parent": "@entry", "head": "returns", "as": "returns"},
        {
            "op": "add_atom",
            "parent": "@returns",
            "kind": "symbol",
            "value": "i32",
        },
        {"op": "create_form", "parent": "@entry", "head": "do", "as": "body"},
        {"op": "create_form", "parent": "@body", "head": "return", "as": "return"},
        {
            "op": "create_form",
            "parent": "@return",
            "head": "const_i32",
            "as": "constant",
        },
        {
            "op": "add_atom",
            "parent": "@constant",
            "kind": "integer",
            "value": 42,
        },
    ]


async def _run(tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONPATH": str(ROOT / "src"),
            "WEAVE_DB_PATH": str(tmp_path / "jacquard.db"),
            "WEAVE_BUILD_ROOT": str(tmp_path / "builds"),
        }
    )
    environment.pop("WEAVEC_BIN", None)
    environment.pop("WEAVEC_SOURCE_ROOT", None)
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "weave_jacquard.mcp_build"],
        env=environment,
        cwd=str(ROOT),
    )

    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        listed = await session.list_tools()
        names = {tool.name for tool in listed.tools}
        assert {"branch_history_page", "branch_activity_summary"} <= names

        initialized = await _call(session, "project_initialize", project="activity-e2e")
        assert isinstance(initialized, list) and len(initialized) == 2
        initial_revision_id = str(initialized[1])
        created = await _call(
            session,
            "program_create",
            project="activity-e2e",
            branch="main",
            document="main.weave",
            program_name="activity-e2e",
        )
        batched = await _call(
            session,
            "node_apply_batch",
            project="activity-e2e",
            branch="main",
            document="main.weave",
            expected_revision_id=created["revision_id"],
            operations=_operations(created["node_id"]),
        )

        first = await _call(
            session,
            "branch_history_page",
            project="activity-e2e",
            branch="main",
            limit=2,
        )
        assert first["branch_head_revision_id"] == batched["revision_id"]
        assert first["returned_count"] == 2
        assert first["has_more"] is True
        assert first["revisions"][0]["operation_count"] == 9
        assert first["revisions"][1]["operation_count"] == 1

        second = await _call(
            session,
            "branch_history_page",
            project="activity-e2e",
            branch="main",
            start_revision_id=first["next_revision_id"],
            limit=2,
        )
        assert second["returned_count"] == 1
        assert second["has_more"] is False
        assert second["revisions"][0]["id"] == initial_revision_id

        summary = await _call(
            session,
            "branch_activity_summary",
            project="activity-e2e",
            branch="main",
        )
        assert summary["revision_count"] == 3
        assert summary["operation_count"] == 10
        assert summary["multi_operation_revision_count"] == 1
        assert summary["revision_count_avoided_by_grouping"] == 8
        assert summary["operation_kind_counts"]["create_form"] == 6
        assert summary["operation_kind_counts"]["add_atom"] == 3


@pytest.mark.real_mcp
def test_real_stdio_mcp_pages_and_summarizes_long_history(tmp_path: Path) -> None:
    asyncio.run(_run(tmp_path))
