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
PROJECT = "revisioned-task-contracts"
TASK_TOOLS = {
    "task_create",
    "task_get",
    "task_list",
    "task_status_set",
    "task_node_apply_batch",
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
        assert set(by_name) >= TASK_TOOLS
        assert {
            "owner",
            "objective",
            "allowed_documents",
            "dependencies",
            "required_tests",
            "acceptance_criteria",
            "expected_revision_id",
        } <= set(_schema(by_name["task_create"])["properties"])
        assert {
            "actor",
            "operations",
            "expected_revision_id",
        } <= set(_schema(by_name["task_node_apply_batch"])["properties"])

        help_payload = await _call_payload(
            session,
            trace,
            "weave_help",
            topic="task_contracts",
        )
        assert help_payload["ok"] is True
        assert "whole-document scope" in help_payload["help"]["scope"]

        await _call(session, trace, "project_initialize", project=PROJECT)
        initial = _main_head(await _call(session, trace, "branch_list", project=PROJECT))
        program = await _call(
            session,
            trace,
            "program_create",
            project=PROJECT,
            branch="main",
            document="main.weave",
            program_name="task-contracts",
            expected_revision_id=initial,
        )
        other = await _call(
            session,
            trace,
            "program_create",
            project=PROJECT,
            branch="main",
            document="other.weave",
            program_name="other",
            expected_revision_id=program["revision_id"],
        )
        documents = await _call(session, trace, "program_list", project=PROJECT)
        main_document = [item for item in documents if item["document"] == "main.weave"]
        assert len(main_document) == 1
        main_root_id = str(main_document[0]["root_node_id"])

        target = await _call(
            session,
            trace,
            "build_target_set",
            project=PROJECT,
            branch="main",
            name="application",
            document="main.weave",
            expected_revision_id=other["revision_id"],
        )
        test = await _call(
            session,
            trace,
            "test_target_set",
            project=PROJECT,
            branch="main",
            name="smoke",
            build_target="application",
            expected_revision_id=target["revision_id"],
        )
        dependency = await _call(
            session,
            trace,
            "task_create",
            project=PROJECT,
            branch="main",
            name="dependency",
            owner="agent-a",
            objective="Complete prerequisite work.",
            allowed_documents=["main.weave"],
            expected_revision_id=test["revision_id"],
        )
        task = await _call(
            session,
            trace,
            "task_create",
            project=PROJECT,
            branch="main",
            name="implementation",
            owner="agent-a",
            objective="Add one scoped structural form.",
            allowed_documents=["main.weave"],
            dependencies=["dependency"],
            required_tests=["smoke"],
            acceptance_criteria=["program validates", "smoke passes"],
            expected_revision_id=dependency["revision_id"],
        )
        assert task["base_revision_id"] == dependency["revision_id"]
        assert task["required_tests"] == ["smoke"]
        assert len(task["contract_hash"]) == 64

        operation = {
            "op": "create_form",
            "parent": main_root_id,
            "head": "do",
            "as": "body",
        }
        blocked = await _call_error(
            session,
            trace,
            "task_node_apply_batch",
            project=PROJECT,
            task="implementation",
            document="main.weave",
            operations=[operation],
            actor="agent-a",
            expected_revision_id=task["revision_id"],
        )
        assert blocked["code"] == "TASK_DEPENDENCIES_INCOMPLETE"

        dependency_complete = await _call(
            session,
            trace,
            "task_status_set",
            project=PROJECT,
            branch="main",
            name="dependency",
            status="complete",
            actor="agent-a",
            expected_revision_id=task["revision_id"],
        )
        wrong_owner = await _call_error(
            session,
            trace,
            "task_node_apply_batch",
            project=PROJECT,
            task="implementation",
            document="main.weave",
            operations=[operation],
            actor="agent-b",
            expected_revision_id=dependency_complete["revision_id"],
        )
        assert wrong_owner["code"] == "TASK_OWNER_MISMATCH"
        wrong_scope = await _call_error(
            session,
            trace,
            "task_node_apply_batch",
            project=PROJECT,
            task="implementation",
            document="other.weave",
            operations=[operation],
            actor="agent-a",
            expected_revision_id=dependency_complete["revision_id"],
        )
        assert wrong_scope["code"] == "TASK_SCOPE_VIOLATION"

        applied = await _call(
            session,
            trace,
            "task_node_apply_batch",
            project=PROJECT,
            task="implementation",
            document="main.weave",
            operations=[operation],
            actor="agent-a",
            expected_revision_id=dependency_complete["revision_id"],
            include_operation_results=True,
        )
        assert applied["task_scope_enforced"] is True
        assert applied["task"] == "implementation"
        assert applied["task_owner"] == "agent-a"
        assert applied["operation_count"] == 1

        resolved = await _call(
            session,
            trace,
            "task_get",
            project=PROJECT,
            name="implementation",
            revision_id=applied["revision_id"],
        )
        assert resolved["allowed_documents"] == ["main.weave"]
        assert resolved["dependencies"] == ["dependency"]
        assert resolved["required_tests"] == ["smoke"]
        listed = await _call(
            session,
            trace,
            "task_list",
            project=PROJECT,
            revision_id=applied["revision_id"],
            limit=10,
        )
        assert [item["name"] for item in listed["tasks"]] == [
            "dependency",
            "implementation",
        ]
        snapshot = await _call(
            session,
            trace,
            "branch_resume_snapshot",
            project=PROJECT,
            revision_id=applied["revision_id"],
            task_limit=10,
        )
        assert [item["name"] for item in snapshot["tasks"]] == [
            "dependency",
            "implementation",
        ]
        assert [item["document"] for item in snapshot["program_documents"]] == [
            "main.weave",
            "other.weave",
        ]
        sources = await _call(
            session,
            trace,
            "program_source_list",
            project=PROJECT,
            revision_id=applied["revision_id"],
        )
        assert sources == ["main.weave", "other.weave"]

        audit = await _call(
            session,
            trace,
            "revision_operations_page",
            project=PROJECT,
            revision_id=applied["revision_id"],
            limit=10,
        )
        assert audit["total_operation_count"] == 1
        operation_payload = audit["operations"][0]["payload"]
        assert operation_payload["task_contract"]["task"] == "implementation"
        assert operation_payload["task_contract"]["actor"] == "agent-a"
        assert operation_payload["task_contract"]["contract_hash"] == applied["task_contract_hash"]
        assert (
            _main_head(await _call(session, trace, "branch_list", project=PROJECT))
            == applied["revision_id"]
        )

    return trace


def _verify_database(tmp_path: Path) -> None:
    with Database(tmp_path / "jacquard.db") as database:
        task_rows = database.connection.execute(
            """SELECT operation_kind, target, payload_json
               FROM operations
               WHERE operation_kind IN (
                   'create_task_contract', 'set_task_status', 'create_form'
               )
               ORDER BY rowid"""
        ).fetchall()
        kinds = [str(row["operation_kind"]) for row in task_rows]
        assert kinds == [
            "create_task_contract",
            "create_task_contract",
            "set_task_status",
            "create_form",
        ]
        create_payload = json.loads(str(task_rows[-1]["payload_json"]))
        assert create_payload["task_contract"]["task"] == "implementation"
        assert create_payload["task_contract"]["owner"] == "agent-a"
        task_snapshots = database.connection.execute(
            """SELECT DISTINCT qualified_name FROM module_snapshots
               WHERE qualified_name LIKE '@task/%'
               ORDER BY qualified_name"""
        ).fetchall()
        assert [str(row["qualified_name"]) for row in task_snapshots] == [
            "@task/dependency",
            "@task/implementation",
        ]


@pytest.mark.real_mcp
def test_real_mcp_enforces_revisioned_task_contracts(tmp_path: Path) -> None:
    trace = asyncio.run(_run(tmp_path))
    _verify_database(tmp_path)
    (tmp_path / "task-contracts-trace.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    task_writes = [entry for entry in trace if entry["tool"] == "task_node_apply_batch"]
    assert len(task_writes) == 4
    assert len([entry for entry in task_writes if entry["payload"]["ok"] is True]) == 1
    assert [
        entry["payload"]["error"]["code"]
        for entry in task_writes
        if entry["payload"]["ok"] is False
    ] == [
        "TASK_DEPENDENCIES_INCOMPLETE",
        "TASK_OWNER_MISMATCH",
        "TASK_SCOPE_VIOLATION",
    ]
