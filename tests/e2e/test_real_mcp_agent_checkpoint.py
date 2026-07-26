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
PROJECT = "agent-checkpoint"
WRITE_TOOL = "branch_checkpoint_create"


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
        assert {
            "branch_checkpoint_create",
            "branch_checkpoint_get",
            "branch_resume_snapshot",
        } <= set(by_name)
        create_properties = _schema(by_name["branch_checkpoint_create"]).get(
            "properties"
        )
        assert isinstance(create_properties, dict)
        assert "expected_revision_id" in create_properties
        assert "next_steps" in create_properties
        get_properties = _schema(by_name["branch_checkpoint_get"]).get("properties")
        assert isinstance(get_properties, dict)
        assert "revision_id" in get_properties

        await _call(session, trace, "project_initialize", project=PROJECT)
        initial = _main_head(
            await _call(session, trace, "branch_list", project=PROJECT)
        )
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

        empty = await _call(
            session,
            trace,
            "branch_checkpoint_get",
            project=PROJECT,
            branch="main",
        )
        assert empty["configured"] is False

        first = await _call(
            session,
            trace,
            WRITE_TOOL,
            project=PROJECT,
            branch="main",
            objective="Complete the checkpoint protocol",
            summary="Publication, resolution, and snapshot composition are implemented.",
            status="in_progress",
            completed=["registry", "MCP tools"],
            next_steps=["qualify real lifecycle"],
            open_questions=["future checkpoint labels"],
            validation=["syntax", "ruff"],
            expected_revision_id=program["revision_id"],
        )
        assert first["base_revision_id"] == program["revision_id"]
        assert first["checkpoint_is_selected_revision"] is True
        assert first["resume"]["arguments"]["revision_id"] == first["revision_id"]

        resolved_first = await _call(
            session,
            trace,
            "branch_checkpoint_get",
            project=PROJECT,
            branch="main",
        )
        assert resolved_first["checkpoint_id"] == first["checkpoint_id"]
        first_snapshot = await _call(
            session,
            trace,
            "branch_resume_snapshot",
            project=PROJECT,
            branch="main",
        )
        assert first_snapshot["agent_checkpoint"]["checkpoint_id"] == first[
            "checkpoint_id"
        ]

        advanced = await _call(
            session,
            trace,
            "node_create_form",
            project=PROJECT,
            branch="main",
            document="main.weave",
            parent_id=program["node_id"],
            head="advanced",
            expected_revision_id=first["revision_id"],
        )
        inherited = await _call(
            session,
            trace,
            "branch_checkpoint_get",
            project=PROJECT,
            branch="main",
        )
        assert inherited["revision_id"] == advanced["revision_id"]
        assert inherited["checkpoint_revision_id"] == first["revision_id"]
        assert inherited["checkpoint_is_selected_revision"] is False
        assert inherited["resume"]["arguments"]["revision_id"] == first["revision_id"]

        second = await _call(
            session,
            trace,
            WRITE_TOOL,
            project=PROJECT,
            branch="main",
            objective="Review and merge the checkpoint protocol",
            summary="All direct and real lifecycle evidence is ready.",
            status="ready_for_review",
            completed=["registry", "MCP tools", "snapshot composition"],
            next_steps=["merge the pull request"],
            validation=["syntax", "ruff", "pytest", "packaged native E2E"],
            expected_revision_id=advanced["revision_id"],
        )
        head = str(second["revision_id"])

        historical = await _call(
            session,
            trace,
            "branch_checkpoint_get",
            project=PROJECT,
            branch="main",
            revision_id=first["revision_id"],
        )
        assert historical["checkpoint_id"] == first["checkpoint_id"]
        assert historical["checkpoint"]["status"] == "in_progress"
        current_snapshot = await _call(
            session,
            trace,
            "branch_resume_snapshot",
            project=PROJECT,
            branch="main",
        )
        assert current_snapshot["agent_checkpoint"]["checkpoint_id"] == second[
            "checkpoint_id"
        ]
        assert current_snapshot["agent_checkpoint"]["checkpoint"]["status"] == (
            "ready_for_review"
        )

        stale = await _call_error(
            session,
            trace,
            WRITE_TOOL,
            project=PROJECT,
            branch="main",
            objective="Stale checkpoint",
            summary="This document must never be retained.",
            expected_revision_id=program["revision_id"],
        )
        assert stale["code"] == "STALE_BRANCH_HEAD"
        invalid = await _call_error(
            session,
            trace,
            WRITE_TOOL,
            project=PROJECT,
            branch="main",
            objective="Invalid checkpoint",
            summary="Invalid status must be rejected.",
            status="unknown",
            expected_revision_id=head,
        )
        assert invalid["code"] == "INVALID_AGENT_CHECKPOINT"
        assert _main_head(
            await _call(session, trace, "branch_list", project=PROJECT)
        ) == head

    return trace


def _verify_database(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "jacquard.db")
    connection.row_factory = sqlite3.Row
    try:
        checkpoint_documents = connection.execute(
            "SELECT id, body FROM documents WHERE title = ? ORDER BY id",
            ("Jacquard agent checkpoint",),
        ).fetchall()
        assert len(checkpoint_documents) == 2
        assert all("Stale checkpoint" not in str(row["body"]) for row in checkpoint_documents)

        operations = connection.execute(
            """SELECT revision_id, payload_json
               FROM operations
               WHERE operation_kind = 'create_agent_checkpoint'
               ORDER BY rowid"""
        ).fetchall()
        assert len(operations) == 2
        for operation in operations:
            payload = json.loads(str(operation["payload_json"]))
            linked = connection.execute(
                """SELECT 1 FROM revision_documents
                   WHERE revision_id = ? AND document_id = ?""",
                (operation["revision_id"], payload["document_id"]),
            ).fetchone()
            assert linked is not None

        orphan_count = connection.execute(
            """SELECT COUNT(*) AS count
               FROM documents d
               LEFT JOIN revision_documents rd ON rd.document_id = d.id
               WHERE rd.document_id IS NULL"""
        ).fetchone()["count"]
        assert orphan_count == 0

        roots = connection.execute(
            """SELECT r.root_hash
               FROM revisions r
               JOIN operations o ON o.revision_id = r.id
               WHERE o.operation_kind IN ('create_program', 'create_agent_checkpoint')
               ORDER BY r.created_at, r.id"""
        ).fetchall()
        assert str(roots[0]["root_hash"]) == str(roots[1]["root_hash"])
    finally:
        connection.close()


@pytest.mark.real_mcp
def test_real_mcp_publishes_and_resolves_agent_checkpoints(tmp_path: Path) -> None:
    trace = asyncio.run(_run(tmp_path))
    _verify_database(tmp_path)
    (tmp_path / "agent-checkpoint-trace.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    writes = [entry for entry in trace if entry["tool"] == WRITE_TOOL]
    assert len(writes) == 4
    assert sum(entry["payload"]["ok"] is True for entry in writes) == 2
    assert {
        entry["payload"]["error"]["code"]
        for entry in writes
        if entry["payload"]["ok"] is False
    } == {"STALE_BRANCH_HEAD", "INVALID_AGENT_CHECKPOINT"}
