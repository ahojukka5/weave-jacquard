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
PROJECT = "project-agent-status"
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
    branch: str,
    expected_revision_id: str,
    objective: str,
    status: str = "in_progress",
) -> Any:
    return await _call(
        session,
        trace,
        "branch_checkpoint_create",
        project=PROJECT,
        branch=branch,
        objective=objective,
        summary=f"Checkpoint for {branch}",
        status=status,
        completed=["one completed item"],
        next_steps=["one next step"],
        validation=["pytest"],
        expected_revision_id=expected_revision_id,
    )


async def _create_form(
    session: ClientSession,
    trace: list[dict[str, Any]],
    *,
    branch: str,
    parent_id: str,
    head: str,
    expected_revision_id: str,
) -> Any:
    return await _call(
        session,
        trace,
        "node_create_form",
        project=PROJECT,
        branch=branch,
        document=DOCUMENT,
        parent_id=parent_id,
        head=head,
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
        assert "project_agent_status_page" in by_name
        properties = _schema(by_name["project_agent_status_page"]).get("properties")
        assert isinstance(properties, dict)
        assert "start_after_branch" in properties
        assert "catalog_id" in properties
        assert "checkpoint_scan_limit" in properties

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
        main_checkpoint = await _checkpoint(
            session,
            trace,
            branch="main",
            expected_revision_id=program["revision_id"],
            objective="Advance main after checkpoint",
        )
        main_head = await _create_form(
            session,
            trace,
            branch="main",
            parent_id=program["node_id"],
            head="main-advanced",
            expected_revision_id=main_checkpoint["revision_id"],
        )

        await _call(
            session,
            trace,
            "branch_create_at_revision",
            project=PROJECT,
            branch="feature",
            revision_id=main_checkpoint["revision_id"],
        )
        feature_checkpoint = await _checkpoint(
            session,
            trace,
            branch="feature",
            expected_revision_id=main_checkpoint["revision_id"],
            objective="Review feature checkpoint",
            status="ready_for_review",
        )

        await _call(
            session,
            trace,
            "branch_create_at_revision",
            project=PROJECT,
            branch="uncheckpointed",
            revision_id=program["revision_id"],
        )
        uncheckpointed_head = await _create_form(
            session,
            trace,
            branch="uncheckpointed",
            parent_id=program["node_id"],
            head="uncheckpointed-edit",
            expected_revision_id=program["revision_id"],
        )

        await _call(
            session,
            trace,
            "branch_create_at_revision",
            project=PROJECT,
            branch="sparse",
            revision_id=program["revision_id"],
        )
        sparse_one = await _create_form(
            session,
            trace,
            branch="sparse",
            parent_id=program["node_id"],
            head="sparse-one",
            expected_revision_id=program["revision_id"],
        )
        sparse_two = await _create_form(
            session,
            trace,
            branch="sparse",
            parent_id=program["node_id"],
            head="sparse-two",
            expected_revision_id=sparse_one["revision_id"],
        )
        sparse_head = await _create_form(
            session,
            trace,
            branch="sparse",
            parent_id=program["node_id"],
            head="sparse-three",
            expected_revision_id=sparse_two["revision_id"],
        )

        first = await _call(
            session,
            trace,
            "project_agent_status_page",
            project=PROJECT,
            limit=2,
            checkpoint_scan_limit=2,
        )
        assert first["branch_catalog_count"] == 4
        assert first["returned_branch_count"] == 2
        assert first["has_more"] is True
        assert first["next_after_branch"] == "main"
        assert [item["branch"] for item in first["branches"]] == ["feature", "main"]

        feature = first["branches"][0]
        assert feature["head_revision_id"] == feature_checkpoint["revision_id"]
        assert feature["checkpoint_state"] == "head"
        assert feature["checkpoint_is_head"] is True
        assert feature["program_state_changed_since_checkpoint"] is False
        assert feature["checkpoint"]["status"] == "ready_for_review"

        main = first["branches"][1]
        assert main["head_revision_id"] == main_head["revision_id"]
        assert main["checkpoint_state"] == "behind_head"
        assert main["revisions_since_checkpoint"] == 1
        assert main["program_state_changed_since_checkpoint"] is True
        assert main["checkpoint"]["checkpoint_revision_id"] == main_checkpoint["revision_id"]

        second = await _call(
            session,
            trace,
            "project_agent_status_page",
            project=PROJECT,
            start_after_branch=first["next_after_branch"],
            catalog_id=first["catalog_id"],
            limit=2,
            checkpoint_scan_limit=2,
        )
        assert second["has_more"] is False
        assert [item["branch"] for item in second["branches"]] == [
            "sparse",
            "uncheckpointed",
        ]
        sparse = second["branches"][0]
        assert sparse["head_revision_id"] == sparse_head["revision_id"]
        assert sparse["checkpoint_state"] == "not_found_within_scan"
        assert sparse["checkpoint_lag_lower_bound"] == 2
        uncheckpointed = second["branches"][1]
        assert uncheckpointed["head_revision_id"] == uncheckpointed_head["revision_id"]
        assert uncheckpointed["checkpoint_state"] == "not_found_within_scan"

        complete = await _call(
            session,
            trace,
            "project_agent_status_page",
            project=PROJECT,
            start_after_branch="sparse",
            catalog_id=first["catalog_id"],
            limit=1,
            checkpoint_scan_limit=10,
        )
        assert complete["branches"][0]["checkpoint_state"] == ("none_in_first_parent_history")
        assert complete["branches"][0]["complete_first_parent_history_scanned"] is True

        later_main = await _create_form(
            session,
            trace,
            branch="main",
            parent_id=program["node_id"],
            head="main-later",
            expected_revision_id=main_head["revision_id"],
        )
        stale = await _call_error(
            session,
            trace,
            "project_agent_status_page",
            project=PROJECT,
            start_after_branch=first["next_after_branch"],
            catalog_id=first["catalog_id"],
            limit=2,
            checkpoint_scan_limit=2,
        )
        assert stale["code"] == "STALE_AGENT_STATUS_CATALOG"

        refreshed = await _call(
            session,
            trace,
            "project_agent_status_page",
            project=PROJECT,
            limit=4,
            checkpoint_scan_limit=3,
        )
        assert refreshed["catalog_id"] != first["catalog_id"]
        refreshed_main = [item for item in refreshed["branches"] if item["branch"] == "main"][0]
        assert refreshed_main["head_revision_id"] == later_main["revision_id"]
        assert refreshed_main["revisions_since_checkpoint"] == 2
        assert "do not prove inactivity" in refreshed["interpretation_note"]

    return trace, {
        "program": program,
        "main_checkpoint": main_checkpoint,
        "main_head": main_head,
        "later_main": later_main,
        "feature_checkpoint": feature_checkpoint,
        "uncheckpointed_head": uncheckpointed_head,
        "sparse_head": sparse_head,
    }


def _verify_read_only_database(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "jacquard.db")
    connection.row_factory = sqlite3.Row
    try:
        status_operations = connection.execute(
            """SELECT COUNT(*) AS count FROM operations
               WHERE operation_kind LIKE '%agent_status%'"""
        ).fetchone()["count"]
        assert status_operations == 0
        branch_count = connection.execute("SELECT COUNT(*) AS count FROM branches").fetchone()[
            "count"
        ]
        assert branch_count == 4
    finally:
        connection.close()


@pytest.mark.real_mcp
def test_real_mcp_pages_project_agent_status(tmp_path: Path) -> None:
    trace, state = asyncio.run(_run(tmp_path))
    _verify_read_only_database(tmp_path)
    (tmp_path / "project-agent-status-trace.json").write_text(
        json.dumps({"trace": trace, "state": state}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    reads = [entry for entry in trace if entry["tool"] == "project_agent_status_page"]
    assert len(reads) == 5
    assert sum(entry["payload"]["ok"] is True for entry in reads) == 4
    assert [
        entry["payload"]["error"]["code"] for entry in reads if entry["payload"]["ok"] is False
    ] == ["STALE_AGENT_STATUS_CATALOG"]
