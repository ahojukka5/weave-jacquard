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
PROJECT = "merge-impact"


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
    tool_name: str,
    **arguments: Any,
) -> Any:
    response = await session.call_tool(tool_name, arguments=arguments)
    payload = _payload(response)
    trace.append({"tool": tool_name, "arguments": arguments, "payload": payload})
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


async def _create_document(
    session: ClientSession,
    trace: list[dict[str, Any]],
    document: str,
) -> dict[str, Any]:
    created = await _call(
        session,
        trace,
        "program_create",
        project=PROJECT,
        branch="main",
        document=document,
        program_name=document,
    )
    atom = await _call(
        session,
        trace,
        "node_add_atom",
        project=PROJECT,
        branch="main",
        document=document,
        parent_id=created["node_id"],
        kind="string",
        value=document,
    )
    return {"root_id": created["node_id"], "atom_id": atom["node_id"]}


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
        assert "branch_merge_impact" in {tool.name for tool in tools.tools}

        await _call(session, trace, "project_initialize", project=PROJECT)
        documents = {
            name: await _create_document(session, trace, name)
            for name in ("main.weave", "lib.weave", "spare.weave", "orphan.weave")
        }
        await _call(
            session,
            trace,
            "build_target_set",
            project=PROJECT,
            branch="main",
            name="application",
            document="main.weave",
            additional_documents=["lib.weave"],
        )
        await _call(
            session,
            trace,
            "build_target_set",
            project=PROJECT,
            branch="main",
            name="main-only",
            document="main.weave",
        )
        await _call(
            session,
            trace,
            "build_target_set",
            project=PROJECT,
            branch="main",
            name="spare",
            document="spare.weave",
        )
        await _call(
            session,
            trace,
            "branch_create",
            project=PROJECT,
            branch="target",
            from_branch="main",
        )
        await _call(
            session,
            trace,
            "branch_create",
            project=PROJECT,
            branch="source",
            from_branch="main",
        )
        target_edit = await _call(
            session,
            trace,
            "node_set_atom",
            project=PROJECT,
            branch="target",
            document="spare.weave",
            node_id=documents["spare.weave"]["atom_id"],
            value="target-spare",
        )
        await _call(
            session,
            trace,
            "node_set_atom",
            project=PROJECT,
            branch="source",
            document="main.weave",
            node_id=documents["main.weave"]["atom_id"],
            value="source-main",
        )
        await _call(
            session,
            trace,
            "node_set_atom",
            project=PROJECT,
            branch="source",
            document="lib.weave",
            node_id=documents["lib.weave"]["atom_id"],
            value="source-lib",
        )
        source_edit = await _call(
            session,
            trace,
            "node_set_atom",
            project=PROJECT,
            branch="source",
            document="orphan.weave",
            node_id=documents["orphan.weave"]["atom_id"],
            value="source-orphan",
        )

        preview = await _call(
            session,
            trace,
            "branch_merge_preview",
            project=PROJECT,
            target_branch="target",
            source_branch="source",
        )
        first = await _call(
            session,
            trace,
            "branch_merge_impact",
            project=PROJECT,
            target_branch="target",
            source_branch="source",
            preview_id=preview["preview_id"],
            limit=1,
        )
        second = await _call(
            session,
            trace,
            "branch_merge_impact",
            project=PROJECT,
            target_branch="target",
            source_branch="source",
            preview_id=preview["preview_id"],
            start_index=first["next_index"],
            limit=1,
        )

        assert first["preview_id"] == preview["preview_id"]
        assert first["changed_program_documents"] == [
            "lib.weave",
            "main.weave",
            "orphan.weave",
        ]
        assert "spare.weave" not in first["changed_program_documents"]
        assert first["candidate_covered_changed_documents"] == [
            "lib.weave",
            "main.weave",
        ]
        assert first["uncovered_changed_documents"] == ["orphan.weave"]
        assert first["total_affected_target_count"] == 2
        assert first["unaffected_target_count"] == 1
        assert first["returned_count"] == 1
        assert first["has_more"] is True
        assert first["affected_targets"][0]["name"] == "application"
        assert first["affected_targets"][0]["changed_source_documents"] == [
            "lib.weave",
            "main.weave",
        ]
        assert second["returned_count"] == 1
        assert second["has_more"] is False
        assert second["affected_targets"][0]["name"] == "main-only"

        branches = await _call(session, trace, "branch_list", project=PROJECT)
        heads = {item["name"]: item["head_revision_id"] for item in branches}
        assert heads["target"] == target_edit["revision_id"]
        assert heads["source"] == source_edit["revision_id"]

    (tmp_path / "merge-impact-trace.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return trace


@pytest.mark.real_mcp
@pytest.mark.real_e2e
def test_real_mcp_reports_affected_targets_and_uncovered_documents(tmp_path: Path) -> None:
    trace = asyncio.run(_run(tmp_path))
    impacts = [entry for entry in trace if entry["tool"] == "branch_merge_impact"]
    assert len(impacts) == 2
    assert [entry["payload"]["result"]["returned_count"] for entry in impacts] == [1, 1]
    assert impacts[0]["payload"]["result"]["uncovered_changed_documents"] == [
        "orphan.weave"
    ]
