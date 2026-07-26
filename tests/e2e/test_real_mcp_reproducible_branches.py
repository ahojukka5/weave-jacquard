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
PROJECT = "reproducible-branches"
WRITE_TOOLS = {"branch_create", "branch_create_at_revision"}


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


async def _call_payload(
    session: ClientSession,
    trace: list[dict[str, Any]],
    tool_name: str,
    **arguments: Any,
) -> dict[str, Any]:
    response = await session.call_tool(tool_name, arguments=arguments)
    payload = _payload(response)
    trace.append({"tool": tool_name, "arguments": arguments, "payload": payload})
    assert _attribute(response, "is_error", "isError") is not True, payload
    return payload


async def _call(
    session: ClientSession,
    trace: list[dict[str, Any]],
    tool_name: str,
    **arguments: Any,
) -> Any:
    payload = await _call_payload(session, trace, tool_name, **arguments)
    assert payload.get("ok") is True, payload
    return payload["result"]


async def _call_error(
    session: ClientSession,
    trace: list[dict[str, Any]],
    tool_name: str,
    **arguments: Any,
) -> dict[str, Any]:
    payload = await _call_payload(session, trace, tool_name, **arguments)
    assert payload.get("ok") is False, payload
    return payload["error"]


def _environment(tmp_path: Path) -> dict[str, str]:
    environment = os.environ.copy()
    python_path = str(ROOT / "src")
    if environment.get("PYTHONPATH"):
        python_path += os.pathsep + environment["PYTHONPATH"]
    environment.update(
        {
            "PYTHONPATH": python_path,
            "WEAVE_DB_PATH": str(tmp_path / "jacquard.db"),
            "WEAVE_BUILD_ROOT": str(tmp_path / "builds"),
        }
    )
    return environment


def _schema(tool: Any) -> dict[str, Any]:
    value = _attribute(tool, "input_schema", "inputSchema")
    assert isinstance(value, dict), tool
    return value


def _heads(branches: list[dict[str, Any]]) -> dict[str, str]:
    return {
        str(branch["name"]): str(branch["head_revision_id"])
        for branch in branches
    }


async def _run(tmp_path: Path) -> list[dict[str, Any]]:
    trace: list[dict[str, Any]] = []
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "weave_jacquard.mcp_build"],
        env=_environment(tmp_path),
        cwd=str(ROOT),
    )
    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        by_name = {tool.name: tool for tool in tools.tools}
        assert set(by_name) >= WRITE_TOOLS
        current_properties = _schema(by_name["branch_create"]).get("properties")
        exact_properties = _schema(by_name["branch_create_at_revision"]).get(
            "properties"
        )
        assert isinstance(current_properties, dict)
        assert isinstance(exact_properties, dict)
        assert "expected_revision_id" in current_properties
        assert "revision_id" in exact_properties

        await _call(session, trace, "project_initialize", project=PROJECT)
        initial_heads = _heads(
            await _call(session, trace, "branch_list", project=PROJECT)
        )
        initial_revision = initial_heads["main"]

        program = await _call(
            session,
            trace,
            "program_create",
            project=PROJECT,
            branch="main",
            document="main.weave",
            program_name=PROJECT,
            expected_revision_id=initial_revision,
        )
        program_revision = str(program["revision_id"])

        feature_revision = await _call(
            session,
            trace,
            "branch_create",
            project=PROJECT,
            branch="feature",
            from_branch="main",
            expected_revision_id=program_revision,
        )
        assert feature_revision == program_revision

        advanced = await _call(
            session,
            trace,
            "node_create_form",
            project=PROJECT,
            branch="main",
            document="main.weave",
            parent_id=program["node_id"],
            head="advanced",
            expected_revision_id=program_revision,
        )
        advanced_revision = str(advanced["revision_id"])

        stale = await _call_error(
            session,
            trace,
            "branch_create",
            project=PROJECT,
            branch="stale",
            from_branch="main",
            expected_revision_id=program_revision,
        )
        assert stale["code"] == "STALE_BRANCH_HEAD"

        historical_revision = await _call(
            session,
            trace,
            "branch_create_at_revision",
            project=PROJECT,
            branch="historical",
            revision_id=program_revision,
        )
        assert historical_revision == program_revision

        current_revision = await _call(
            session,
            trace,
            "branch_create",
            project=PROJECT,
            branch="current-copy",
            from_branch="main",
        )
        assert current_revision == advanced_revision

        duplicate = await _call_error(
            session,
            trace,
            "branch_create_at_revision",
            project=PROJECT,
            branch="historical",
            revision_id=initial_revision,
        )
        assert duplicate["code"] == "DUPLICATE_BRANCH"

        heads = _heads(await _call(session, trace, "branch_list", project=PROJECT))
        assert heads == {
            "current-copy": advanced_revision,
            "feature": program_revision,
            "historical": program_revision,
            "main": advanced_revision,
        }

        feature_source = await _call(
            session,
            trace,
            "program_render",
            project=PROJECT,
            branch="feature",
            document="main.weave",
        )
        main_source = await _call(
            session,
            trace,
            "program_render",
            project=PROJECT,
            branch="main",
            document="main.weave",
        )
        assert "advanced" not in feature_source["source"]
        assert "advanced" in main_source["source"]

    (tmp_path / "reproducible-branch-create-trace.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return trace


@pytest.mark.real_mcp
def test_real_mcp_creates_reproducible_branches(tmp_path: Path) -> None:
    trace = asyncio.run(_run(tmp_path))
    writes = [entry for entry in trace if entry["tool"] in WRITE_TOOLS]
    assert len(writes) == 5
    successful = [entry for entry in writes if entry["payload"]["ok"] is True]
    rejected = [entry for entry in writes if entry["payload"]["ok"] is False]
    assert len(successful) == 3
    assert len(rejected) == 2
    assert {entry["payload"]["error"]["code"] for entry in rejected} == {
        "DUPLICATE_BRANCH",
        "STALE_BRANCH_HEAD",
    }
