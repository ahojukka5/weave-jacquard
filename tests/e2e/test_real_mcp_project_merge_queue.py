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
PROJECT = "project-merge-queue"
DOCUMENT = "main.weave"
TOOL = "project_merge_queue_page"


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
    environment.pop("WEAVEC_BIN", None)
    environment.pop("WEAVEC_SOURCE_ROOT", None)
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
) -> Any:
    return await _call(
        session,
        trace,
        "branch_checkpoint_create",
        project=PROJECT,
        branch=branch,
        objective=objective,
        summary=f"Checkpoint for {branch}",
        status="in_progress",
        completed=["prepared merge candidate"],
        next_steps=["run merge preflight"],
        validation=["syntax"],
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
            TOOL,
            "branch_merge_preview",
            "branch_merge_preflight",
            "branch_checkpoint_create",
        } <= set(by_name)
        properties = _schema(by_name[TOOL]).get("properties")
        assert isinstance(properties, dict)
        assert {
            "target_branch",
            "start_after_source",
            "catalog_id",
            "limit",
            "checkpoint_scan_limit",
            "conflict_limit",
            "changed_document_limit",
        } <= set(properties)

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
        atom = await _call(
            session,
            trace,
            "node_add_atom",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            parent_id=program["node_id"],
            kind="string",
            value="base",
            expected_revision_id=program["revision_id"],
        )
        base_revision = str(atom["revision_id"])
        for branch in ("clean", "conflict"):
            await _call(
                session,
                trace,
                "branch_create_at_revision",
                project=PROJECT,
                branch=branch,
                revision_id=base_revision,
            )

        clean_one = await _call(
            session,
            trace,
            "program_create",
            project=PROJECT,
            branch="clean",
            document="clean-one.weave",
            program_name="clean-one",
            expected_revision_id=base_revision,
        )
        clean_two = await _call(
            session,
            trace,
            "program_create",
            project=PROJECT,
            branch="clean",
            document="clean-two.weave",
            program_name="clean-two",
            expected_revision_id=clean_one["revision_id"],
        )
        clean_checkpoint = await _checkpoint(
            session,
            trace,
            branch="clean",
            expected_revision_id=clean_two["revision_id"],
            objective="Review clean source",
        )
        conflict_checkpoint = await _checkpoint(
            session,
            trace,
            branch="conflict",
            expected_revision_id=base_revision,
            objective="Resolve conflicting atom",
        )
        conflict_head = await _call(
            session,
            trace,
            "node_set_atom",
            project=PROJECT,
            branch="conflict",
            document=DOCUMENT,
            node_id=atom["node_id"],
            value="source-value",
            expected_revision_id=conflict_checkpoint["revision_id"],
        )
        target_head = await _call(
            session,
            trace,
            "node_set_atom",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            node_id=atom["node_id"],
            value="target-value",
            expected_revision_id=base_revision,
        )
        await _call(
            session,
            trace,
            "branch_create_at_revision",
            project=PROJECT,
            branch="noop",
            revision_id=target_head["revision_id"],
        )

        branches_before = await _call(
            session,
            trace,
            "branch_list",
            project=PROJECT,
        )
        heads_before = {
            item["name"]: item["head_revision_id"] for item in branches_before
        }

        first = await _call(
            session,
            trace,
            TOOL,
            project=PROJECT,
            target_branch="main",
            limit=2,
            checkpoint_scan_limit=20,
            conflict_limit=1,
            changed_document_limit=1,
        )
        assert first["source_catalog_count"] == 3
        assert first["returned_source_count"] == 2
        assert first["has_more"] is True
        assert first["next_after_source"] == "conflict"
        assert [item["source_branch"] for item in first["sources"]] == [
            "clean",
            "conflict",
        ]

        clean = first["sources"][0]
        assert clean["classification"] == "clean_changes"
        assert clean["changed_document_count"] == 2
        assert clean["changed_documents"] == ["clean-one.weave"]
        assert clean["changed_documents_truncated"] is True
        assert clean["source_checkpoint"]["checkpoint_state"] == "head"
        assert clean["source_checkpoint"]["checkpoint"][
            "checkpoint_revision_id"
        ] == clean_checkpoint["revision_id"]
        assert clean["preflight"]["arguments"]["preview_id"] == clean["preview_id"]

        replayed_preview = await _call(
            session,
            trace,
            clean["full_preview"]["tool"],
            **clean["full_preview"]["arguments"],
        )
        assert replayed_preview["preview_id"] == clean["preview_id"]
        assert replayed_preview["target_head_revision_id"] == target_head["revision_id"]
        assert replayed_preview["source_head_revision_id"] == clean_checkpoint[
            "revision_id"
        ]

        conflict = first["sources"][1]
        assert conflict["classification"] == "conflicted"
        assert conflict["mergeable"] is False
        assert conflict["conflict_count"] >= 1
        assert atom["node_id"] in conflict["conflicts"][0]
        assert conflict["preflight"] is None
        assert conflict["source_checkpoint"]["checkpoint_state"] == "behind_head"
        assert conflict["source_checkpoint"]["revisions_since_checkpoint"] == 1
        assert conflict["source_head_revision_id"] == conflict_head["revision_id"]

        second = await _call(
            session,
            trace,
            TOOL,
            project=PROJECT,
            target_branch="main",
            start_after_source=first["next_after_source"],
            catalog_id=first["catalog_id"],
            limit=2,
            checkpoint_scan_limit=20,
            conflict_limit=1,
            changed_document_limit=1,
        )
        assert second["has_more"] is False
        assert [item["source_branch"] for item in second["sources"]] == ["noop"]
        noop = second["sources"][0]
        assert noop["classification"] == "clean_no_changes"
        assert noop["mergeable"] is True
        assert noop["changed_document_count"] == 0
        assert noop["merged_root_hash"] == noop["target_root_hash"]
        assert noop["source_checkpoint"]["checkpoint_state"] == (
            "none_in_first_parent_history"
        )

        branches_after_reads = await _call(
            session,
            trace,
            "branch_list",
            project=PROJECT,
        )
        heads_after_reads = {
            item["name"]: item["head_revision_id"] for item in branches_after_reads
        }
        assert heads_after_reads == heads_before

        later_clean = await _call(
            session,
            trace,
            "program_create",
            project=PROJECT,
            branch="clean",
            document="clean-later.weave",
            program_name="clean-later",
            expected_revision_id=clean_checkpoint["revision_id"],
        )
        stale = await _call_error(
            session,
            trace,
            TOOL,
            project=PROJECT,
            target_branch="main",
            start_after_source=first["next_after_source"],
            catalog_id=first["catalog_id"],
            limit=2,
        )
        assert stale["code"] == "STALE_PROJECT_MERGE_QUEUE_CATALOG"
        refreshed = await _call(
            session,
            trace,
            TOOL,
            project=PROJECT,
            target_branch="main",
            limit=3,
            checkpoint_scan_limit=20,
        )
        assert refreshed["catalog_id"] != first["catalog_id"]
        refreshed_clean = [
            item for item in refreshed["sources"] if item["source_branch"] == "clean"
        ][0]
        assert refreshed_clean["source_head_revision_id"] == later_clean["revision_id"]
        assert refreshed_clean["source_checkpoint"]["checkpoint_state"] == "behind_head"
        assert refreshed_clean["source_checkpoint"]["revisions_since_checkpoint"] == 1
        assert "does not represent merge priority" in refreshed["priority_note"]
        assert "structural preview success only" in refreshed["readiness_note"]

    return trace, {
        "clean_checkpoint": clean_checkpoint,
        "conflict_checkpoint": conflict_checkpoint,
        "conflict_head": conflict_head,
        "target_head": target_head,
        "later_clean": later_clean,
    }


def _verify_read_only_database(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "jacquard.db")
    connection.row_factory = sqlite3.Row
    try:
        merge_operations = connection.execute(
            """SELECT COUNT(*) AS count FROM operations
               WHERE operation_kind LIKE '%merge%'"""
        ).fetchone()["count"]
        assert merge_operations == 0
        branch_count = connection.execute(
            "SELECT COUNT(*) AS count FROM branches"
        ).fetchone()["count"]
        assert branch_count == 4
    finally:
        connection.close()


@pytest.mark.real_mcp
def test_real_mcp_pages_project_merge_queue(tmp_path: Path) -> None:
    trace, state = asyncio.run(_run(tmp_path))
    _verify_read_only_database(tmp_path)
    (tmp_path / "project-merge-queue-trace.json").write_text(
        json.dumps({"trace": trace, "state": state}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    reads = [entry for entry in trace if entry["tool"] == TOOL]
    assert len(reads) == 4
    assert sum(entry["payload"]["ok"] is True for entry in reads) == 3
    assert [
        entry["payload"]["error"]["code"]
        for entry in reads
        if entry["payload"]["ok"] is False
    ] == ["STALE_PROJECT_MERGE_QUEUE_CATALOG"]
