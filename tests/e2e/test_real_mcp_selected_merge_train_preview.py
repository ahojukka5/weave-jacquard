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
PROJECT = "selected-merge-train-preview"
DOCUMENT = "main.weave"
TOOL = "selected_merge_train_preview"


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
        assert {TOOL, "project_merge_queue_page", "branch_merge_preflight"} <= set(by_name)
        properties = _schema(by_name[TOOL]).get("properties")
        assert isinstance(properties, dict)
        assert {
            "target_branch",
            "sources",
            "catalog_id",
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
        revision_id = str(program["revision_id"])
        atoms: list[str] = []
        for _ in range(3):
            added = await _call(
                session,
                trace,
                "node_add_atom",
                project=PROJECT,
                branch="main",
                document=DOCUMENT,
                parent_id=program["node_id"],
                kind="integer",
                value=0,
                expected_revision_id=revision_id,
            )
            revision_id = str(added["revision_id"])
            atoms.append(str(added["node_id"]))
        base_revision = revision_id
        target = await _call(
            session,
            trace,
            "node_set_atom",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            node_id=atoms[1],
            value=1,
            expected_revision_id=base_revision,
        )
        target_head = str(target["revision_id"])

        for branch in (
            "alpha",
            "beta",
            "bridge",
            "same-one",
            "same-two",
            "unselected",
        ):
            await _call(
                session,
                trace,
                "branch_create_at_revision",
                project=PROJECT,
                branch=branch,
                revision_id=target_head,
            )
        await _call(
            session,
            trace,
            "branch_create_at_revision",
            project=PROJECT,
            branch="legacy",
            revision_id=base_revision,
        )

        changes = {
            "alpha": (atoms[0], 10, target_head),
            "beta": (atoms[0], 20, target_head),
            "same-one": (atoms[2], 30, target_head),
            "same-two": (atoms[2], 30, target_head),
            "bridge": (atoms[1], 2, target_head),
            "legacy": (atoms[1], 2, base_revision),
        }
        heads: dict[str, str] = {}
        for branch, (node_id, value, expected) in changes.items():
            changed = await _call(
                session,
                trace,
                "node_set_atom",
                project=PROJECT,
                branch=branch,
                document=DOCUMENT,
                node_id=node_id,
                value=value,
                expected_revision_id=expected,
            )
            heads[branch] = str(changed["revision_id"])

        queue = await _call(
            session,
            trace,
            "project_merge_queue_page",
            project=PROJECT,
            target_branch="main",
            limit=10,
        )
        catalog_id = str(queue["catalog_id"])
        heads_before = {
            item["name"]: item["head_revision_id"]
            for item in await _call(
                session,
                trace,
                "branch_list",
                project=PROJECT,
            )
        }

        introduced = await _call(
            session,
            trace,
            TOOL,
            project=PROJECT,
            target_branch="main",
            sources=["alpha", "beta", "same-one"],
            catalog_id=catalog_id,
            conflict_limit=1,
            changed_document_limit=1,
        )
        assert introduced["train_complete"] is False
        assert introduced["conflict_step_index"] == 1
        assert introduced["remaining_sources_not_simulated"] == ["same-one"]
        assert introduced["steps"][0]["source_head_revision_id"] == heads["alpha"]
        assert introduced["steps"][1]["source_head_revision_id"] == heads["beta"]
        assert introduced["steps"][1]["relation_to_original_preview"] == (
            "order_introduced_conflict"
        )
        assert atoms[0] in introduced["steps"][1]["conflicts"][0]
        assert introduced["first_publication_candidate"]["arguments"]["source_branch"] == "alpha"

        redundant = await _call(
            session,
            trace,
            TOOL,
            project=PROJECT,
            target_branch="main",
            sources=["same-one", "same-two"],
            catalog_id=catalog_id,
        )
        assert redundant["train_complete"] is True
        assert redundant["steps"][1]["no_changes"] is True
        assert (
            redundant["steps"][1]["virtual_target_root_before"]
            == redundant["steps"][1]["virtual_target_root_after"]
        )
        assert redundant["steps"][1]["publication_requires_refresh_after_prior_step"] is True

        removed = await _call(
            session,
            trace,
            TOOL,
            project=PROJECT,
            target_branch="main",
            sources=["bridge", "legacy"],
            catalog_id=catalog_id,
        )
        assert removed["train_complete"] is True
        assert removed["steps"][1]["source_head_revision_id"] == heads["legacy"]
        assert removed["steps"][1]["original_preview_mergeable"] is False
        assert removed["steps"][1]["train_step_mergeable"] is True
        assert removed["steps"][1]["relation_to_original_preview"] == ("order_removed_conflict")
        assert removed["steps"][1]["no_changes"] is True
        assert "no compiler, preflight, or merge publication ran" in removed["simulation_note"]

        heads_after = {
            item["name"]: item["head_revision_id"]
            for item in await _call(
                session,
                trace,
                "branch_list",
                project=PROJECT,
            )
        }
        assert heads_after == heads_before

        advanced = await _call(
            session,
            trace,
            "program_create",
            project=PROJECT,
            branch="unselected",
            document="later.weave",
            program_name="later",
            expected_revision_id=target_head,
        )
        stale = await _call_error(
            session,
            trace,
            TOOL,
            project=PROJECT,
            target_branch="main",
            sources=["alpha"],
            catalog_id=catalog_id,
        )
        assert stale["code"] == "STALE_SELECTED_MERGE_TRAIN_CATALOG"

    return trace, {
        "base_revision": base_revision,
        "target_head": target_head,
        "heads": heads,
        "advanced": advanced,
    }


def _verify_read_only_database(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "jacquard.db")
    connection.row_factory = sqlite3.Row
    try:
        merge_revisions = connection.execute(
            "SELECT COUNT(*) AS count FROM revisions WHERE parent2_id IS NOT NULL"
        ).fetchone()["count"]
        assert merge_revisions == 0
        train_operations = connection.execute(
            """SELECT COUNT(*) AS count FROM operations
               WHERE operation_kind LIKE '%merge_train%'"""
        ).fetchone()["count"]
        assert train_operations == 0
        branch_count = connection.execute("SELECT COUNT(*) AS count FROM branches").fetchone()[
            "count"
        ]
        assert branch_count == 8
    finally:
        connection.close()


@pytest.mark.real_mcp
def test_real_mcp_simulates_selected_merge_trains(tmp_path: Path) -> None:
    trace, state = asyncio.run(_run(tmp_path))
    _verify_read_only_database(tmp_path)
    (tmp_path / "selected-merge-train-preview-trace.json").write_text(
        json.dumps({"trace": trace, "state": state}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    train_calls = [entry for entry in trace if entry["tool"] == TOOL]
    assert len(train_calls) == 4
    assert sum(entry["payload"]["ok"] is True for entry in train_calls) == 3
    assert train_calls[-1]["payload"]["error"]["code"] == ("STALE_SELECTED_MERGE_TRAIN_CATALOG")
