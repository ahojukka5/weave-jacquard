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
PROJECT = "context-policy-concurrency"
WRITE_TOOLS = {"context_add", "merge_policy_set"}


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

        context = await _call(
            session,
            trace,
            "context_add",
            project=PROJECT,
            branch="main",
            scope_kind="document",
            scope_name="main.weave",
            title="Shared invariant",
            body="The result is immutable.",
            expected_revision_id=initial,
        )
        assert context["base_revision_id"] == initial

        reused = await _call(
            session,
            trace,
            "context_add",
            project=PROJECT,
            branch="main",
            scope_kind="document",
            scope_name="main.weave",
            title="Shared invariant",
            body="The result is immutable.",
            expected_revision_id=context["revision_id"],
        )
        assert reused["base_revision_id"] == context["revision_id"]
        assert reused["document_id"] == context["document_id"]

        policy = await _call(
            session,
            trace,
            "merge_policy_set",
            project=PROJECT,
            branch="main",
            require_preflight=True,
            require_affected_validation=True,
            allow_uncovered_documents=False,
            max_affected_targets=5,
            expected_revision_id=reused["revision_id"],
        )
        assert policy["base_revision_id"] == reused["revision_id"]
        head = str(policy["revision_id"])

        resolved = await _call(
            session,
            trace,
            "merge_policy_get",
            project=PROJECT,
            branch="main",
        )
        assert resolved["policy_hash"] == policy["policy_hash"]
        assert resolved["max_affected_targets"] == 5
        context_rows = await _call(
            session,
            trace,
            "context_get",
            project=PROJECT,
            branch="main",
            scope_name="main.weave",
        )
        assert any(row["id"] == context["document_id"] for row in context_rows)

        stale_context = await _call_error(
            session,
            trace,
            "context_add",
            project=PROJECT,
            branch="main",
            scope_kind="document",
            scope_name="main.weave",
            title="Stale context",
            body="Must not survive.",
            expected_revision_id=initial,
        )
        assert stale_context["code"] == "STALE_BRANCH_HEAD"

        stale_policy = await _call_error(
            session,
            trace,
            "merge_policy_set",
            project=PROJECT,
            branch="main",
            require_preflight=True,
            require_affected_validation=True,
            allow_uncovered_documents=False,
            max_affected_targets=6,
            expected_revision_id=reused["revision_id"],
        )
        assert stale_policy["code"] == "STALE_BRANCH_HEAD"
        assert _main_head(await _call(session, trace, "branch_list", project=PROJECT)) == head

        context_two = await _call(
            session,
            trace,
            "context_add",
            project=PROJECT,
            branch="main",
            scope_kind="symbol",
            scope_name="main",
            title="Second invariant",
            body="Unprepared writes still compare-and-set.",
        )
        assert context_two["base_revision_id"] == head
        head = str(context_two["revision_id"])

        policy_two = await _call(
            session,
            trace,
            "merge_policy_set",
            project=PROJECT,
            branch="main",
            require_preflight=True,
            require_affected_validation=True,
            allow_uncovered_documents=False,
            max_affected_targets=4,
        )
        assert policy_two["base_revision_id"] == head
        assert (
            _main_head(await _call(session, trace, "branch_list", project=PROJECT))
            == policy_two["revision_id"]
        )

    return trace


def _verify_database(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "jacquard.db")
    connection.row_factory = sqlite3.Row
    try:
        documents = connection.execute(
            "SELECT id, title FROM documents ORDER BY title, id"
        ).fetchall()
        titles = [str(row["title"]) for row in documents]
        assert titles.count("Shared invariant") == 1
        assert "Second invariant" in titles
        assert "Stale context" not in titles
        assert titles.count("Jacquard merge policy") == 2
        orphan_count = connection.execute(
            """SELECT COUNT(*) AS count
               FROM documents d
               LEFT JOIN revision_documents rd ON rd.document_id = d.id
               WHERE rd.document_id IS NULL"""
        ).fetchone()["count"]
        assert orphan_count == 0
        operations = connection.execute(
            """SELECT operation_kind, payload_json
               FROM operations
               WHERE operation_kind IN ('add_context', 'set_merge_policy')"""
        ).fetchall()
        assert len(operations) == 5
        for row in operations:
            payload = json.loads(str(row["payload_json"]))
            linked = connection.execute(
                "SELECT 1 FROM revision_documents WHERE document_id = ? LIMIT 1",
                (payload["document_id"],),
            ).fetchone()
            assert linked is not None
    finally:
        connection.close()


@pytest.mark.real_mcp
def test_real_mcp_publishes_context_and_policy_atomically(tmp_path: Path) -> None:
    trace = asyncio.run(_run(tmp_path))
    _verify_database(tmp_path)
    (tmp_path / "context-policy-concurrency-trace.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    writes = [entry for entry in trace if entry["tool"] in WRITE_TOOLS]
    assert len(writes) == 7
    successful = [entry for entry in writes if entry["payload"]["ok"] is True]
    rejected = [entry for entry in writes if entry["payload"]["ok"] is False]
    assert len(successful) == 5
    assert len(rejected) == 2
    assert all("base_revision_id" in entry["payload"]["result"] for entry in successful)
    assert {entry["payload"]["error"]["code"] for entry in rejected} == {"STALE_BRANCH_HEAD"}
