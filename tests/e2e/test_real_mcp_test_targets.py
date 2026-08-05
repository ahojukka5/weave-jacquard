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
PROJECT = "revisioned-test-targets"
TEST_TOOLS = {
    "test_target_set",
    "test_target_get",
    "test_target_list",
    "test_target_delete",
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
        assert set(by_name) >= TEST_TOOLS
        for tool_name in ("test_target_set", "test_target_delete"):
            properties = _schema(by_name[tool_name]).get("properties")
            assert isinstance(properties, dict), by_name[tool_name]
            assert "expected_revision_id" in properties
        set_properties = _schema(by_name["test_target_set"])["properties"]
        assert {
            "build_target",
            "arguments",
            "stdin",
            "expected_exit_code",
            "expected_stdout",
            "expected_stderr",
            "timeout_ms",
            "max_memory_bytes",
            "max_output_bytes",
            "max_file_bytes",
            "tags",
        } <= set(set_properties)
        list_properties = _schema(by_name["test_target_list"])["properties"]
        assert {"revision_id", "start_after_name", "limit"} <= set(list_properties)

        help_payload = await _call_payload(
            session,
            trace,
            "weave_help",
            topic="test_targets",
        )
        assert help_payload["ok"] is True
        assert "no program execution" in help_payload["help"]["execution"]

        await _call(session, trace, "project_initialize", project=PROJECT)
        initial = _main_head(await _call(session, trace, "branch_list", project=PROJECT))
        program = await _call(
            session,
            trace,
            "program_create",
            project=PROJECT,
            branch="main",
            document="main.weave",
            program_name="revisioned-test-targets",
            expected_revision_id=initial,
        )
        target = await _call(
            session,
            trace,
            "build_target_set",
            project=PROJECT,
            branch="main",
            name="application",
            document="main.weave",
            expected_revision_id=program["revision_id"],
        )
        created = await _call(
            session,
            trace,
            "test_target_set",
            project=PROJECT,
            branch="main",
            name="cli-smoke",
            build_target="application",
            arguments=["--count", "3"],
            stdin="input\n",
            expected_exit_code=7,
            expected_stdout="done\n",
            expected_stderr="warning\n",
            timeout_ms=2_000,
            max_memory_bytes=33_554_432,
            max_output_bytes=8_192,
            max_file_bytes=4_096,
            tags=["smoke", "cli/fast"],
            expected_revision_id=target["revision_id"],
        )
        assert created["base_revision_id"] == target["revision_id"]
        assert created["network_policy"] == "deny"
        assert created["filesystem_policy"] == "isolated"
        assert created["definition_hash"]

        resolved = await _call(
            session,
            trace,
            "test_target_get",
            project=PROJECT,
            name="cli-smoke",
            revision_id=created["revision_id"],
        )
        assert resolved["arguments"] == ["--count", "3"]
        assert resolved["expected_stdout"] == "done\n"
        assert resolved["tags"] == ["smoke", "cli/fast"]
        assert resolved["definition_hash"] == created["definition_hash"]
        listed = await _call(
            session,
            trace,
            "test_target_list",
            project=PROJECT,
            revision_id=created["revision_id"],
            limit=1,
        )
        assert listed["format"] == "weave-test-target-list-v1"
        assert listed["total_test_target_count"] == 1
        assert listed["returned_test_target_count"] == 1
        assert listed["test_targets_truncated"] is False
        assert [item["name"] for item in listed["test_targets"]] == ["cli-smoke"]
        summary = listed["test_targets"][0]
        assert summary["definition_hash"] == created["definition_hash"]
        assert summary["expected_stdout_bytes"] == 5
        assert "expected_stdout" not in summary

        source_documents = await _call(
            session,
            trace,
            "program_source_list",
            project=PROJECT,
            revision_id=created["revision_id"],
        )
        assert source_documents == ["main.weave"]
        snapshot = await _call(
            session,
            trace,
            "branch_resume_snapshot",
            project=PROJECT,
            branch="main",
            revision_id=created["revision_id"],
            test_target_limit=10,
        )
        assert [item["document"] for item in snapshot["program_documents"]] == ["main.weave"]
        assert [item["name"] for item in snapshot["test_targets"]] == ["cli-smoke"]
        assert snapshot["test_targets"][0]["expected_stdout_bytes"] == 5
        assert snapshot["test_targets"][0]["definition_hash"] == created["definition_hash"]

        stale = await _call_error(
            session,
            trace,
            "test_target_set",
            project=PROJECT,
            branch="main",
            name="stale",
            build_target="application",
            expected_revision_id=target["revision_id"],
        )
        assert stale["code"] == "STALE_BRANCH_HEAD"

        updated = await _call(
            session,
            trace,
            "test_target_set",
            project=PROJECT,
            branch="main",
            name="cli-smoke",
            build_target="application",
            arguments=["--count", "4"],
            expected_stdout="updated\n",
            tags=["smoke"],
            expected_revision_id=created["revision_id"],
        )
        assert updated["base_revision_id"] == created["revision_id"]
        assert updated["root_node_id"] == created["root_node_id"]
        assert updated["definition_hash"] != created["definition_hash"]
        current = await _call(
            session,
            trace,
            "test_target_get",
            project=PROJECT,
            name="cli-smoke",
        )
        assert current["arguments"] == ["--count", "4"]
        assert current["expected_stdout"] == "updated\n"
        assert current["definition_hash"] == updated["definition_hash"]
        assert (
            _main_head(await _call(session, trace, "branch_list", project=PROJECT))
            == updated["revision_id"]
        )

    return trace


def _verify_database(tmp_path: Path) -> None:
    with Database(tmp_path / "jacquard.db") as database:
        connection = database.connection
        operations = connection.execute(
            """SELECT revision_id, operation_kind, target
               FROM operations
               WHERE operation_kind IN ('set_test_target', 'delete_test_target')
               ORDER BY rowid"""
        ).fetchall()
        assert [str(row["operation_kind"]) for row in operations] == [
            "set_test_target",
            "set_test_target",
        ]
        assert all(str(row["target"]) == "@test-target/cli-smoke" for row in operations)
        stale_rows = connection.execute(
            """SELECT COUNT(*) AS count FROM module_snapshots
               WHERE qualified_name = '@test-target/stale'"""
        ).fetchone()["count"]
        assert stale_rows == 0
        for row in operations:
            snapshot = connection.execute(
                """SELECT ast_json FROM module_snapshots
                   WHERE revision_id = ? AND qualified_name = '@test-target/cli-smoke'""",
                (row["revision_id"],),
            ).fetchone()
            assert snapshot is not None
            root = json.loads(str(snapshot["ast_json"]))
            assert root["kind"] == "list"


@pytest.mark.real_mcp
def test_real_mcp_publishes_revisioned_test_targets(tmp_path: Path) -> None:
    trace = asyncio.run(_run(tmp_path))
    _verify_database(tmp_path)
    (tmp_path / "test-targets-trace.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    test_writes = [entry for entry in trace if entry["tool"] == "test_target_set"]
    assert len(test_writes) == 3
    assert len([entry for entry in test_writes if entry["payload"]["ok"] is True]) == 2
    rejected = [entry for entry in test_writes if entry["payload"]["ok"] is False]
    assert [entry["payload"]["error"]["code"] for entry in rejected] == ["STALE_BRANCH_HEAD"]
