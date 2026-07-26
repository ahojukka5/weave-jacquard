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
PROJECT = "revision-diff"
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
        assert "revision_diff_page" in {tool.name for tool in tools.tools}

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
        left = await _call(
            session,
            trace,
            "node_create_form",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            parent_id=created["node_id"],
            head="left",
        )
        right = await _call(
            session,
            trace,
            "node_create_form",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            parent_id=created["node_id"],
            head="right",
        )
        number = await _call(
            session,
            trace,
            "node_add_atom",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            parent_id=left["node_id"],
            kind="integer",
            value=1,
        )
        removed = await _call(
            session,
            trace,
            "node_add_atom",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            parent_id=left["node_id"],
            kind="string",
            value="remove",
        )
        base_revision = str(removed["revision_id"])

        await _call(
            session,
            trace,
            "node_set_atom",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            node_id=number["node_id"],
            value=2,
        )
        added = await _call(
            session,
            trace,
            "node_add_atom",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            parent_id=right["node_id"],
            kind="boolean",
            value=True,
        )
        await _call(
            session,
            trace,
            "node_move",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            node_id=number["node_id"],
            new_parent_id=right["node_id"],
        )
        target = await _call(
            session,
            trace,
            "node_delete",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            node_id=removed["node_id"],
        )
        target_revision = str(target["revision_id"])

        pages: list[dict[str, Any]] = []
        start_index = 0
        while True:
            page = await _call(
                session,
                trace,
                "revision_diff_page",
                project=PROJECT,
                branch="main",
                document=DOCUMENT,
                base_revision_id=base_revision,
                start_index=start_index,
                limit=2,
            )
            pages.append(page)
            if not page["has_more"]:
                break
            start_index = int(page["next_index"])

        changes = [change for page in pages for change in page["changes"]]
        by_id = {change["node_id"]: change for change in changes}
        assert [page["returned_count"] for page in pages] == [2, 2, 1]
        assert len(changes) == len(by_id) == 5
        assert pages[0]["base_revision_id"] == base_revision
        assert pages[0]["target_revision_id"] == target_revision
        assert pages[0]["target_revision_is_branch_head"] is True
        assert by_id[number["node_id"]]["change_kinds"] == [
            "value_changed",
            "parent_changed",
            "position_changed",
        ]
        assert by_id[number["node_id"]]["before"]["value"] == 1
        assert by_id[number["node_id"]]["after"]["value"] == 2
        assert by_id[added["node_id"]]["change_kinds"] == ["added"]
        assert by_id[removed["node_id"]]["change_kinds"] == ["removed"]

        reverse = await _call(
            session,
            trace,
            "revision_diff_page",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            base_revision_id=target_revision,
            target_revision_id=base_revision,
            limit=200,
        )
        reverse_by_id = {change["node_id"]: change for change in reverse["changes"]}
        assert reverse["target_revision_is_branch_head"] is False
        assert reverse_by_id[added["node_id"]]["change_kinds"] == ["removed"]
        assert reverse_by_id[removed["node_id"]]["change_kinds"] == ["added"]
        assert reverse_by_id[number["node_id"]]["before"]["value"] == 2
        assert reverse_by_id[number["node_id"]]["after"]["value"] == 1

    (tmp_path / "revision-diff-trace.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return trace


@pytest.mark.real_mcp
@pytest.mark.real_e2e
def test_real_mcp_pages_stable_node_revision_diff(tmp_path: Path) -> None:
    trace = asyncio.run(_run(tmp_path))
    pages = [entry for entry in trace if entry["tool"] == "revision_diff_page"]
    assert len(pages) == 4
    assert [entry["payload"]["result"]["returned_count"] for entry in pages[:3]] == [
        2,
        2,
        1,
    ]
    assert pages[3]["arguments"]["target_revision_id"]
