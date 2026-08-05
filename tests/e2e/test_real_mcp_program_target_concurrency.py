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
PROJECT = "program-target-concurrency"
PROGRAM_TOOLS = {"program_create", "program_import"}
TARGET_TOOLS = {"build_target_set", "build_target_delete"}
WRITE_TOOLS = PROGRAM_TOOLS | TARGET_TOOLS

LIBRARY = """(program
  (name \"library\")
  (version \"0.1\"))
"""
SUPPORT = LIBRARY.replace('name "library"', 'name "support"')


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


def _main_head(branches: list[dict[str, Any]]) -> str:
    main = [branch for branch in branches if branch["name"] == "main"]
    assert len(main) == 1, branches
    return str(main[0]["head_revision_id"])


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
        for tool_name in WRITE_TOOLS:
            properties = _schema(by_name[tool_name]).get("properties")
            assert isinstance(properties, dict), by_name[tool_name]
            assert "expected_revision_id" in properties, (tool_name, properties)

        await _call(session, trace, "project_initialize", project=PROJECT)
        initial = _main_head(await _call(session, trace, "branch_list", project=PROJECT))

        program = await _call(
            session,
            trace,
            "program_create",
            project=PROJECT,
            branch="main",
            document="main.weave",
            program_name=PROJECT,
            expected_revision_id=initial,
        )
        assert program["base_revision_id"] == initial

        library = await _call(
            session,
            trace,
            "program_import",
            project=PROJECT,
            branch="main",
            document="library.weave",
            source=LIBRARY,
            expected_revision_id=program["revision_id"],
        )
        assert library["base_revision_id"] == program["revision_id"]

        target = await _call(
            session,
            trace,
            "build_target_set",
            project=PROJECT,
            branch="main",
            name="application",
            document="main.weave",
            additional_documents=["library.weave"],
            expected_revision_id=library["revision_id"],
        )
        assert target["base_revision_id"] == library["revision_id"]

        deleted = await _call(
            session,
            trace,
            "build_target_delete",
            project=PROJECT,
            branch="main",
            name="application",
            expected_revision_id=target["revision_id"],
        )
        assert deleted["base_revision_id"] == target["revision_id"]
        head = str(deleted["revision_id"])

        stale_program = await _call_error(
            session,
            trace,
            "program_import",
            project=PROJECT,
            branch="main",
            document="stale.weave",
            source=SUPPORT,
            expected_revision_id=program["revision_id"],
        )
        assert stale_program["code"] == "STALE_BRANCH_HEAD"

        stale_target = await _call_error(
            session,
            trace,
            "build_target_set",
            project=PROJECT,
            branch="main",
            name="stale",
            document="main.weave",
            expected_revision_id=target["revision_id"],
        )
        assert stale_target["code"] == "STALE_BRANCH_HEAD"
        assert _main_head(await _call(session, trace, "branch_list", project=PROJECT)) == head

        support = await _call(
            session,
            trace,
            "program_import",
            project=PROJECT,
            branch="main",
            document="support.weave",
            source=SUPPORT,
        )
        assert support["base_revision_id"] == head
        head = str(support["revision_id"])

        unprepared_target = await _call(
            session,
            trace,
            "build_target_set",
            project=PROJECT,
            branch="main",
            name="application",
            document="main.weave",
            additional_documents=["library.weave", "support.weave"],
        )
        assert unprepared_target["base_revision_id"] == head
        assert (
            _main_head(await _call(session, trace, "branch_list", project=PROJECT))
            == unprepared_target["revision_id"]
        )

    (tmp_path / "program-target-concurrency-trace.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return trace


@pytest.mark.real_mcp
def test_real_mcp_enforces_program_and_target_concurrency(tmp_path: Path) -> None:
    trace = asyncio.run(_run(tmp_path))
    writes = [entry for entry in trace if entry["tool"] in WRITE_TOOLS]
    assert len(writes) == 8
    successful = [entry for entry in writes if entry["payload"]["ok"] is True]
    rejected = [entry for entry in writes if entry["payload"]["ok"] is False]
    assert len(successful) == 6
    assert len(rejected) == 2
    assert all("base_revision_id" in entry["payload"]["result"] for entry in successful)
    assert {entry["payload"]["error"]["code"] for entry in rejected} == {"STALE_BRANCH_HEAD"}
