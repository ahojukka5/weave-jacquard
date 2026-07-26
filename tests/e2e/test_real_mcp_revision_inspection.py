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


async def _call(
    session: ClientSession,
    trace: list[dict[str, Any]],
    name: str,
    **arguments: Any,
) -> Any:
    response = await session.call_tool(name, arguments=arguments)
    payload = _payload(response)
    trace.append({"tool": name, "arguments": arguments, "payload": payload})
    assert _attribute(response, "is_error", "isError") is not True, payload
    assert payload.get("ok") is True, payload
    return payload.get("result")


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
    environment.pop("WEAVEC_BIN", None)
    environment.pop("WEAVEC_SOURCE_ROOT", None)
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
        assert "node_inspect" in {tool.name for tool in tools.tools}

        await _call(session, trace, "project_initialize", project="historical-inspection")
        created = await _call(
            session,
            trace,
            "program_create",
            project="historical-inspection",
            branch="main",
            document="main.weave",
            program_name="historical-inspection",
        )
        atom = await _call(
            session,
            trace,
            "node_add_atom",
            project="historical-inspection",
            branch="main",
            document="main.weave",
            parent_id=created["node_id"],
            kind="symbol",
            value="before",
        )
        historical_revision = str(atom["revision_id"])
        repaired = await _call(
            session,
            trace,
            "node_set_atom",
            project="historical-inspection",
            branch="main",
            document="main.weave",
            node_id=atom["node_id"],
            value="after",
        )

        current = await _call(
            session,
            trace,
            "node_inspect",
            project="historical-inspection",
            branch="main",
            document="main.weave",
            node_id=atom["node_id"],
        )
        historical = await _call(
            session,
            trace,
            "node_inspect",
            project="historical-inspection",
            branch="main",
            document="main.weave",
            node_id=atom["node_id"],
            revision_id=historical_revision,
        )

        assert current["revision_id"] == repaired["revision_id"]
        assert current["revision_is_branch_head"] is True
        assert current["subtree"]["value"] == "after"
        assert historical["revision_id"] == historical_revision
        assert historical["branch_head_revision_id"] == repaired["revision_id"]
        assert historical["revision_is_branch_head"] is False
        assert historical["node_id"] == current["node_id"]
        assert historical["subtree"]["value"] == "before"

    (tmp_path / "revision-inspection-trace.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return trace


@pytest.mark.real_mcp
@pytest.mark.real_e2e
def test_real_mcp_inspects_current_and_historical_stable_node(tmp_path: Path) -> None:
    trace = asyncio.run(_run(tmp_path))
    inspections = [entry for entry in trace if entry["tool"] == "node_inspect"]
    assert len(inspections) == 2
    assert "revision_id" not in inspections[0]["arguments"]
    assert "revision_id" in inspections[1]["arguments"]
