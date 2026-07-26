from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "agent-checkpoint-timeline"


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


async def _checkpoint(
    session: ClientSession,
    trace: list[dict[str, Any]],
    *,
    expected_revision_id: str,
    objective: str,
    summary: str,
    status: str = "in_progress",
    completed: list[str] | None = None,
    next_steps: list[str] | None = None,
    open_questions: list[str] | None = None,
    validation: list[str] | None = None,
) -> Any:
    return await _call(
        session,
        trace,
        "branch_checkpoint_create",
        project=PROJECT,
        branch="main",
        objective=objective,
        summary=summary,
        status=status,
        completed=completed,
        next_steps=next_steps,
        open_questions=open_questions,
        validation=validation,
        expected_revision_id=expected_revision_id,
    )


async def _run(tmp_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
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
        assert {
            "branch_checkpoint_history_page",
            "branch_checkpoint_compare",
        } <= set(by_name)
        page_properties = _schema(by_name["branch_checkpoint_history_page"]).get(
            "properties"
        )
        assert isinstance(page_properties, dict)
        assert "start_revision_id" in page_properties
        assert "revision_scan_limit" in page_properties
        compare_properties = _schema(by_name["branch_checkpoint_compare"]).get(
            "properties"
        )
        assert isinstance(compare_properties, dict)
        assert "base_checkpoint_revision_id" in compare_properties
        assert "target_checkpoint_revision_id" in compare_properties

        await _call(session, trace, "project_initialize", project=PROJECT)
        program = await _call(
            session,
            trace,
            "program_create",
            project=PROJECT,
            branch="main",
            document="main.weave",
            program_name=PROJECT,
        )
        first = await _checkpoint(
            session,
            trace,
            expected_revision_id=program["revision_id"],
            objective="Build checkpoint supervision",
            summary="Initial handoff before timeline implementation.",
            completed=["checkpoint protocol"],
            next_steps=["implement timeline", "add tests"],
            open_questions=["how should sparse history be bounded?"],
            validation=["syntax"],
        )
        edit_one = await _call(
            session,
            trace,
            "node_create_form",
            project=PROJECT,
            branch="main",
            document="main.weave",
            parent_id=program["node_id"],
            head="timeline",
            expected_revision_id=first["revision_id"],
        )
        edit_two = await _call(
            session,
            trace,
            "node_create_form",
            project=PROJECT,
            branch="main",
            document="main.weave",
            parent_id=program["node_id"],
            head="comparison",
            expected_revision_id=edit_one["revision_id"],
        )
        second = await _checkpoint(
            session,
            trace,
            expected_revision_id=edit_two["revision_id"],
            objective="Qualify checkpoint supervision",
            summary="Timeline and comparison services are implemented.",
            completed=["checkpoint protocol", "timeline implementation"],
            next_steps=["add tests", "write documentation"],
            validation=["syntax", "ruff"],
        )
        edit_three = await _call(
            session,
            trace,
            "node_create_form",
            project=PROJECT,
            branch="main",
            document="main.weave",
            parent_id=program["node_id"],
            head="qualified",
            expected_revision_id=second["revision_id"],
        )
        third = await _checkpoint(
            session,
            trace,
            expected_revision_id=edit_three["revision_id"],
            objective="Merge checkpoint supervision",
            summary="All supervisory evidence is ready.",
            status="ready_for_review",
            completed=[
                "checkpoint protocol",
                "timeline implementation",
                "direct tests",
            ],
            next_steps=["merge pull request"],
            validation=["syntax", "ruff", "pytest"],
        )

        first_page = await _call(
            session,
            trace,
            "branch_checkpoint_history_page",
            project=PROJECT,
            branch="main",
            limit=2,
            revision_scan_limit=20,
        )
        assert first_page["returned_checkpoint_count"] == 2
        assert first_page["checkpoint_limit_reached"] is True
        assert first_page["scan_limit_reached"] is False
        assert [
            entry["checkpoint_revision_id"] for entry in first_page["checkpoints"]
        ] == [third["revision_id"], second["revision_id"]]
        assert first_page["checkpoints"][0]["resume"]["arguments"] == {
            "project": PROJECT,
            "branch": "main",
            "revision_id": third["revision_id"],
        }

        second_page = await _call(
            session,
            trace,
            "branch_checkpoint_history_page",
            project=PROJECT,
            branch="main",
            start_revision_id=first_page["next_revision_id"],
            limit=2,
            revision_scan_limit=20,
        )
        assert second_page["returned_checkpoint_count"] == 1
        assert second_page["checkpoints"][0]["checkpoint_revision_id"] == first[
            "revision_id"
        ]
        assert second_page["has_more"] is False

        sparse = await _call(
            session,
            trace,
            "branch_checkpoint_history_page",
            project=PROJECT,
            branch="main",
            start_revision_id=edit_two["revision_id"],
            limit=10,
            revision_scan_limit=1,
        )
        assert sparse["returned_checkpoint_count"] == 0
        assert sparse["scan_limit_reached"] is True
        assert sparse["next_revision_id"] == edit_one["revision_id"]

        comparison = await _call(
            session,
            trace,
            "branch_checkpoint_compare",
            project=PROJECT,
            base_checkpoint_revision_id=first["revision_id"],
            target_checkpoint_revision_id=third["revision_id"],
        )
        assert comparison["changed"] is True
        assert comparison["program_state_changed"] is True
        assert comparison["status"]["target"] == "ready_for_review"
        assert comparison["list_deltas"]["completed"]["added"] == [
            "timeline implementation",
            "direct tests",
        ]
        assert comparison["list_deltas"]["next_steps"]["removed"] == [
            "implement timeline",
            "add tests",
        ]
        assert comparison["list_deltas"]["open_questions"]["removed"] == [
            "how should sparse history be bounded?"
        ]
        assert "does not prove completion" in comparison["interpretation_note"]

        same = await _call(
            session,
            trace,
            "branch_checkpoint_compare",
            project=PROJECT,
            base_checkpoint_revision_id=second["revision_id"],
            target_checkpoint_revision_id=second["revision_id"],
        )
        assert same["changed"] is False
        assert same["program_state_changed"] is False

        invalid = await _call_error(
            session,
            trace,
            "branch_checkpoint_compare",
            project=PROJECT,
            base_checkpoint_revision_id=edit_one["revision_id"],
            target_checkpoint_revision_id=second["revision_id"],
        )
        assert invalid["code"] == "CHECKPOINT_REVISION_REQUIRED"

    return trace, {
        "first": first,
        "second": second,
        "third": third,
        "edit_one": edit_one,
        "edit_two": edit_two,
        "edit_three": edit_three,
    }


def _verify_read_only_database(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "jacquard.db")
    connection.row_factory = sqlite3.Row
    try:
        checkpoints = connection.execute(
            """SELECT COUNT(*) AS count FROM operations
               WHERE operation_kind = 'create_agent_checkpoint'"""
        ).fetchone()["count"]
        assert checkpoints == 3
        comparison_operations = connection.execute(
            """SELECT COUNT(*) AS count FROM operations
               WHERE operation_kind LIKE '%checkpoint_compare%'
                  OR operation_kind LIKE '%checkpoint_history%'"""
        ).fetchone()["count"]
        assert comparison_operations == 0
    finally:
        connection.close()


@pytest.mark.real_mcp
def test_real_mcp_reads_checkpoint_timeline_and_progress(tmp_path: Path) -> None:
    trace, state = asyncio.run(_run(tmp_path))
    _verify_read_only_database(tmp_path)
    (tmp_path / "agent-checkpoint-timeline-trace.json").write_text(
        json.dumps({"trace": trace, "state": state}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    timeline_reads = [
        entry for entry in trace if entry["tool"] == "branch_checkpoint_history_page"
    ]
    comparison_reads = [
        entry for entry in trace if entry["tool"] == "branch_checkpoint_compare"
    ]
    assert len(timeline_reads) == 3
    assert len(comparison_reads) == 3
    assert sum(entry["payload"]["ok"] is True for entry in comparison_reads) == 2
