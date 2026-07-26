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
PROJECT = "revision-reads"
DOCUMENT = "main.weave"


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
    name: str,
    **arguments: Any,
) -> dict[str, Any]:
    response = await session.call_tool(name, arguments=arguments)
    payload = _payload(response)
    trace.append({"tool": name, "arguments": arguments, "payload": payload})
    assert _attribute(response, "is_error", "isError") is not True, payload
    assert payload.get("ok") is True, payload
    return payload


async def _call(
    session: ClientSession,
    trace: list[dict[str, Any]],
    name: str,
    **arguments: Any,
) -> Any:
    return (await _call_payload(session, trace, name, **arguments))["result"]


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
        names = {tool.name for tool in tools.tools}
        assert {"program_render", "node_find"} <= names

        await _call(session, trace, "project_initialize", project=PROJECT)
        created = await _call(
            session,
            trace,
            "program_create",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            program_name=PROJECT,
        )
        atom = await _call(
            session,
            trace,
            "node_add_atom",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            parent_id=created["node_id"],
            kind="integer",
            value=1,
        )
        historical_revision = str(atom["revision_id"])
        repaired = await _call(
            session,
            trace,
            "node_set_atom",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            node_id=atom["node_id"],
            value=2,
        )
        current_revision = str(repaired["revision_id"])

        current_render = await _call(
            session,
            trace,
            "program_render",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            annotated=False,
        )
        historical_render = await _call(
            session,
            trace,
            "program_render",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            annotated=False,
            revision_id=historical_revision,
        )
        assert current_render["revision_id"] == current_revision
        assert current_render["revision_is_branch_head"] is True
        assert "2" in current_render["source"]
        assert historical_render["revision_id"] == historical_revision
        assert historical_render["branch_head_revision_id"] == current_revision
        assert historical_render["revision_is_branch_head"] is False
        assert "1" in historical_render["source"]

        current_find = await _call_payload(
            session,
            trace,
            "node_find",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            value=2,
        )
        historical_find = await _call_payload(
            session,
            trace,
            "node_find",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            value=1,
            revision_id=historical_revision,
        )
        absent_find = await _call_payload(
            session,
            trace,
            "node_find",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            value=1,
        )
        assert isinstance(current_find["result"], list)
        assert current_find["matched_count"] == 1
        assert current_find["result"][0]["node_id"] == atom["node_id"]
        assert current_find["revision_id"] == current_revision
        assert historical_find["matched_count"] == 1
        assert historical_find["result"][0]["node_id"] == atom["node_id"]
        assert historical_find["revision_id"] == historical_revision
        assert historical_find["revision_is_branch_head"] is False
        assert absent_find["result"] == []
        assert absent_find["matched_count"] == 0
        assert absent_find["revision_id"] == current_revision
        assert absent_find["revision_is_branch_head"] is True

    (tmp_path / "revision-reads-trace.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return trace


@pytest.mark.real_mcp
@pytest.mark.real_e2e
def test_real_mcp_reproduces_historical_render_and_search(tmp_path: Path) -> None:
    trace = asyncio.run(_run(tmp_path))
    renders = [entry for entry in trace if entry["tool"] == "program_render"]
    finds = [entry for entry in trace if entry["tool"] == "node_find"]
    assert len(renders) == 2
    assert len(finds) == 3
    assert renders[0]["payload"]["result"]["revision_is_branch_head"] is True
    assert renders[1]["payload"]["result"]["revision_is_branch_head"] is False
    assert finds[1]["payload"]["revision_is_branch_head"] is False
    assert finds[2]["payload"]["result"] == []
    assert finds[2]["payload"]["matched_count"] == 0
