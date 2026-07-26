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
PROJECT = "single-node-concurrency"
DOCUMENT = "main.weave"
NODE_TOOLS = {
    "node_create_form",
    "node_add_atom",
    "node_set_atom",
    "node_move",
    "node_wrap",
    "node_delete",
}


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
    return payload


async def _call(
    session: ClientSession,
    trace: list[dict[str, Any]],
    name: str,
    **arguments: Any,
) -> Any:
    payload = await _call_payload(session, trace, name, **arguments)
    assert payload.get("ok") is True, payload
    return payload["result"]


async def _call_error(
    session: ClientSession,
    trace: list[dict[str, Any]],
    name: str,
    **arguments: Any,
) -> dict[str, Any]:
    payload = await _call_payload(session, trace, name, **arguments)
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
        assert NODE_TOOLS <= set(by_name)
        for name in NODE_TOOLS:
            properties = _schema(by_name[name]).get("properties")
            assert isinstance(properties, dict), by_name[name]
            assert "expected_revision_id" in properties, (name, properties)

        await _call(session, trace, "project_initialize", project=PROJECT)
        program = await _call(
            session,
            trace,
            "program_create",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            program_name=PROJECT,
        )
        initial_revision = str(program["revision_id"])
        head = initial_revision

        left = await _call(
            session,
            trace,
            "node_create_form",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            parent_id=program["node_id"],
            head="left",
            expected_revision_id=head,
        )
        assert left["base_revision_id"] == head
        head = str(left["revision_id"])

        right = await _call(
            session,
            trace,
            "node_create_form",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            parent_id=program["node_id"],
            head="right",
            expected_revision_id=head,
        )
        assert right["base_revision_id"] == head
        head = str(right["revision_id"])

        atom = await _call(
            session,
            trace,
            "node_add_atom",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            parent_id=left["node_id"],
            kind="integer",
            value=1,
            expected_revision_id=head,
        )
        assert atom["base_revision_id"] == head
        head = str(atom["revision_id"])

        changed = await _call(
            session,
            trace,
            "node_set_atom",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            node_id=atom["node_id"],
            value=2,
            expected_revision_id=head,
        )
        assert changed["base_revision_id"] == head
        assert changed["node_id"] == atom["node_id"]
        head = str(changed["revision_id"])

        moved = await _call(
            session,
            trace,
            "node_move",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            node_id=atom["node_id"],
            new_parent_id=right["node_id"],
            expected_revision_id=head,
        )
        assert moved["base_revision_id"] == head
        assert moved["node_id"] == atom["node_id"]
        head = str(moved["revision_id"])

        wrapped = await _call(
            session,
            trace,
            "node_wrap",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            node_id=atom["node_id"],
            head="wrapped",
            expected_revision_id=head,
        )
        assert wrapped["base_revision_id"] == head
        assert wrapped["wrapped_node_id"] == atom["node_id"]
        head = str(wrapped["revision_id"])

        deleted = await _call(
            session,
            trace,
            "node_delete",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            node_id=wrapped["node_id"],
            expected_revision_id=head,
        )
        assert deleted["base_revision_id"] == head
        head = str(deleted["revision_id"])

        before_stale = await _call(
            session,
            trace,
            "branch_list",
            project=PROJECT,
        )
        assert _main_head(before_stale) == head
        stale = await _call_error(
            session,
            trace,
            "node_create_form",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            parent_id=program["node_id"],
            head="stale",
            expected_revision_id=initial_revision,
        )
        assert stale["code"] == "STALE_BRANCH_HEAD"
        after_stale = await _call(
            session,
            trace,
            "branch_list",
            project=PROJECT,
        )
        assert _main_head(after_stale) == head

        unprepared = await _call(
            session,
            trace,
            "node_add_atom",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            parent_id=program["node_id"],
            kind="integer",
            value=7,
        )
        assert unprepared["base_revision_id"] == head
        assert unprepared["revision_id"] != head

    (tmp_path / "single-node-concurrency-trace.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return trace


@pytest.mark.real_mcp
@pytest.mark.real_e2e
def test_real_mcp_enforces_single_node_branch_concurrency(tmp_path: Path) -> None:
    trace = asyncio.run(_run(tmp_path))
    writes = [entry for entry in trace if entry["tool"] in NODE_TOOLS]
    assert len(writes) == 9
    successful = [entry for entry in writes if entry["payload"]["ok"] is True]
    rejected = [entry for entry in writes if entry["payload"]["ok"] is False]
    assert len(successful) == 8
    assert len(rejected) == 1
    assert all("base_revision_id" in entry["payload"]["result"] for entry in successful)
    assert rejected[0]["payload"]["error"]["code"] == "STALE_BRANCH_HEAD"
