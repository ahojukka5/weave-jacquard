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

from weave_frontend.database import Database

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "immutable-revert"
REVERT_TOOLS = {"branch_revert_preview", "branch_revert"}


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
        assert set(by_name) >= REVERT_TOOLS
        revert_schema = _attribute(
            by_name["branch_revert"],
            "input_schema",
            "inputSchema",
        )
        assert isinstance(revert_schema, dict)
        assert "preview_id" in revert_schema.get("required", [])

        help_payload = await _call_payload(
            session,
            trace,
            "weave_help",
            topic="revert",
        )
        assert help_payload["ok"] is True
        assert "never resets" in help_payload["help"]["history"]

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
        selected = await _call(
            session,
            trace,
            "node_create_form",
            project=PROJECT,
            branch="main",
            document="main.weave",
            parent_id=program["node_id"],
            head="do",
            expected_revision_id=program["revision_id"],
        )
        later = await _call(
            session,
            trace,
            "program_create",
            project=PROJECT,
            branch="main",
            document="other.weave",
            program_name="independent-other",
            expected_revision_id=selected["revision_id"],
        )

        stale_preview = await _call(
            session,
            trace,
            "branch_revert_preview",
            project=PROJECT,
            branch="main",
            revision_id=selected["revision_id"],
        )
        assert stale_preview["revertible"] is True
        assert stale_preview["changed_documents"] == ["main.weave"]
        advanced = await _call(
            session,
            trace,
            "program_create",
            project=PROJECT,
            branch="main",
            document="third.weave",
            program_name="independent-third",
            expected_revision_id=later["revision_id"],
        )
        stale_error = await _call_error(
            session,
            trace,
            "branch_revert",
            project=PROJECT,
            branch="main",
            revision_id=selected["revision_id"],
            preview_id=stale_preview["preview_id"],
        )
        assert stale_error["code"] == "STALE_REVERT_PREVIEW"
        assert (
            _main_head(await _call(session, trace, "branch_list", project=PROJECT))
            == advanced["revision_id"]
        )

        preview = await _call(
            session,
            trace,
            "branch_revert_preview",
            project=PROJECT,
            branch="main",
            revision_id=selected["revision_id"],
        )
        assert preview["revertible"] is True
        assert preview["would_change_branch"] is True
        result = await _call(
            session,
            trace,
            "branch_revert",
            project=PROJECT,
            branch="main",
            revision_id=selected["revision_id"],
            preview_id=preview["preview_id"],
            author="real-mcp-recovery-agent",
        )
        assert result["parent_revision_id"] == advanced["revision_id"]
        assert result["history_rewritten"] is False
        assert result["changed_documents"] == ["main.weave"]
        assert (
            _main_head(await _call(session, trace, "branch_list", project=PROJECT))
            == result["revision_id"]
        )

        main_render = await _call(
            session,
            trace,
            "program_render",
            project=PROJECT,
            branch="main",
            document="main.weave",
            annotated=False,
        )
        other_render = await _call(
            session,
            trace,
            "program_render",
            project=PROJECT,
            branch="main",
            document="other.weave",
            annotated=False,
        )
        third_render = await _call(
            session,
            trace,
            "program_render",
            project=PROJECT,
            branch="main",
            document="third.weave",
            annotated=False,
        )
        assert "(do" not in main_render["source"]
        assert "independent-other" in other_render["source"]
        assert "independent-third" in third_render["source"]

    (tmp_path / "immutable-revert-trace.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return trace


def _verify_database(tmp_path: Path) -> None:
    with Database(tmp_path / "jacquard.db") as database:
        row = database.connection.execute(
            """SELECT r.id, r.parent1_id, r.parent2_id, o.operation_kind,
                      o.target, o.payload_json
               FROM revisions r
               JOIN operations o ON o.revision_id = r.id
               WHERE o.operation_kind = 'revert'"""
        ).fetchone()
        assert row is not None
        assert row["parent1_id"] is not None
        assert row["parent2_id"] is None
        assert row["target"] == "main"
        payload = json.loads(str(row["payload_json"]))
        assert payload["format"] == "weave-revert-preview-v1"
        assert payload["reviewed_branch_head_revision_id"] == row["parent1_id"]
        assert payload["prospective_root_hash"]
        assert payload["changed_documents"] == ["main.weave"]


@pytest.mark.real_mcp
@pytest.mark.real_e2e
def test_real_mcp_previews_and_publishes_immutable_revert(tmp_path: Path) -> None:
    trace = asyncio.run(_run(tmp_path))
    _verify_database(tmp_path)
    previews = [entry for entry in trace if entry["tool"] == "branch_revert_preview"]
    publications = [entry for entry in trace if entry["tool"] == "branch_revert"]
    assert len(previews) == 2
    assert len(publications) == 2
    assert publications[0]["payload"]["error"]["code"] == "STALE_REVERT_PREVIEW"
    assert publications[1]["payload"]["result"]["history_rewritten"] is False
