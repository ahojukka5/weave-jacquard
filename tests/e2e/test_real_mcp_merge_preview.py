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


async def _call(
    session: ClientSession,
    trace: list[dict[str, Any]],
    name: str,
    **arguments: Any,
) -> Any:
    response = await session.call_tool(name, arguments=arguments)
    payload = _payload(response)
    trace.append({"tool": name, "arguments": arguments, "payload": payload})
    assert _attribute(response, "is_error", "isError") is not True, payload
    assert payload.get("ok") is True, payload
    return payload.get("result")


async def _call_error(
    session: ClientSession,
    trace: list[dict[str, Any]],
    name: str,
    **arguments: Any,
) -> dict[str, Any]:
    response = await session.call_tool(name, arguments=arguments)
    payload = _payload(response)
    trace.append({"tool": name, "arguments": arguments, "payload": payload})
    assert payload.get("ok") is False, payload
    error = payload.get("error")
    assert isinstance(error, dict)
    return error


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


async def _create_clean_branches(
    session: ClientSession,
    trace: list[dict[str, Any]],
    project: str,
) -> dict[str, Any]:
    await _call(session, trace, "project_initialize", project=project)
    created = await _call(
        session,
        trace,
        "program_create",
        project=project,
        branch="main",
        document=DOCUMENT,
        program_name=project,
    )
    await _call(
        session,
        trace,
        "branch_create",
        project=project,
        branch="target",
        from_branch="main",
    )
    await _call(
        session,
        trace,
        "branch_create",
        project=project,
        branch="source",
        from_branch="main",
    )
    target = await _call(
        session,
        trace,
        "node_create_form",
        project=project,
        branch="target",
        document=DOCUMENT,
        parent_id=created["node_id"],
        head="target_only",
    )
    source = await _call(
        session,
        trace,
        "node_create_form",
        project=project,
        branch="source",
        document=DOCUMENT,
        parent_id=created["node_id"],
        head="source_only",
    )
    return {
        "root_id": created["node_id"],
        "target_head": target["revision_id"],
        "source_head": source["revision_id"],
        "source_node_id": source["node_id"],
    }


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
        names = {tool.name for tool in tools.tools}
        assert {"branch_merge_preview", "branch_merge"} <= names

        clean = await _create_clean_branches(session, trace, "reviewed-merge")
        preview = await _call(
            session,
            trace,
            "branch_merge_preview",
            project="reviewed-merge",
            target_branch="target",
            source_branch="source",
        )
        assert preview["mergeable"] is True
        assert preview["conflicts"] == []
        assert preview["changed_documents"] == [DOCUMENT]
        assert preview["target_head_revision_id"] == clean["target_head"]
        assert preview["source_head_revision_id"] == clean["source_head"]
        assert preview["document_changes"][0]["changed_node_count"] == 3
        assert preview["document_changes"][0]["change_kind_counts"] == {
            "added": 2,
            "child_count_changed": 1,
        }

        branches_before = await _call(
            session,
            trace,
            "branch_list",
            project="reviewed-merge",
        )
        heads_before = {item["name"]: item["head_revision_id"] for item in branches_before}
        assert heads_before["target"] == clean["target_head"]

        merged = await _call(
            session,
            trace,
            "branch_merge",
            project="reviewed-merge",
            target_branch="target",
            source_branch="source",
            preview_id=preview["preview_id"],
        )
        assert merged["preview_enforced"] is True
        assert merged["preview_id"] == preview["preview_id"]
        assert merged["reviewed_target_head_revision_id"] == clean["target_head"]
        assert merged["reviewed_source_head_revision_id"] == clean["source_head"]
        assert merged["changed_symbols"] == [DOCUMENT]
        inspected = await _call(
            session,
            trace,
            "node_inspect",
            project="reviewed-merge",
            branch="target",
            document=DOCUMENT,
            node_id=clean["source_node_id"],
        )
        assert inspected["head"] == "source_only"

        stale = await _create_clean_branches(session, trace, "stale-merge")
        stale_preview = await _call(
            session,
            trace,
            "branch_merge_preview",
            project="stale-merge",
            target_branch="target",
            source_branch="source",
        )
        await _call(
            session,
            trace,
            "node_create_form",
            project="stale-merge",
            branch="source",
            document=DOCUMENT,
            parent_id=stale["root_id"],
            head="source_advanced",
        )
        stale_error = await _call_error(
            session,
            trace,
            "branch_merge",
            project="stale-merge",
            target_branch="target",
            source_branch="source",
            preview_id=stale_preview["preview_id"],
        )
        assert stale_error["code"] == "STALE_MERGE_PREVIEW"
        stale_branches = await _call(
            session,
            trace,
            "branch_list",
            project="stale-merge",
        )
        stale_heads = {item["name"]: item["head_revision_id"] for item in stale_branches}
        assert stale_heads["target"] == stale["target_head"]
        assert stale_heads["source"] != stale["source_head"]

        await _call(session, trace, "project_initialize", project="conflict-merge")
        conflict_program = await _call(
            session,
            trace,
            "program_create",
            project="conflict-merge",
            branch="main",
            document=DOCUMENT,
            program_name="conflict-merge",
        )
        conflict_atom = await _call(
            session,
            trace,
            "node_add_atom",
            project="conflict-merge",
            branch="main",
            document=DOCUMENT,
            parent_id=conflict_program["node_id"],
            kind="string",
            value="base",
        )
        await _call(
            session,
            trace,
            "branch_create",
            project="conflict-merge",
            branch="target",
            from_branch="main",
        )
        await _call(
            session,
            trace,
            "branch_create",
            project="conflict-merge",
            branch="source",
            from_branch="main",
        )
        target_conflict = await _call(
            session,
            trace,
            "node_set_atom",
            project="conflict-merge",
            branch="target",
            document=DOCUMENT,
            node_id=conflict_atom["node_id"],
            value="target",
        )
        await _call(
            session,
            trace,
            "node_set_atom",
            project="conflict-merge",
            branch="source",
            document=DOCUMENT,
            node_id=conflict_atom["node_id"],
            value="source",
        )
        conflict_preview = await _call(
            session,
            trace,
            "branch_merge_preview",
            project="conflict-merge",
            target_branch="target",
            source_branch="source",
        )
        assert conflict_preview["mergeable"] is False
        assert conflict_preview["conflicts"]
        assert conflict_preview["merged_root_hash"] is None
        conflict_error = await _call_error(
            session,
            trace,
            "branch_merge",
            project="conflict-merge",
            target_branch="target",
            source_branch="source",
            preview_id=conflict_preview["preview_id"],
        )
        assert conflict_error["code"] == "MERGE_CONFLICT"
        conflict_branches = await _call(
            session,
            trace,
            "branch_list",
            project="conflict-merge",
        )
        conflict_heads = {item["name"]: item["head_revision_id"] for item in conflict_branches}
        assert conflict_heads["target"] == target_conflict["revision_id"]

    (tmp_path / "merge-preview-trace.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return trace


@pytest.mark.real_mcp
@pytest.mark.real_e2e
def test_real_mcp_enforces_reviewed_merge_heads(tmp_path: Path) -> None:
    trace = asyncio.run(_run(tmp_path))
    previews = [entry for entry in trace if entry["tool"] == "branch_merge_preview"]
    merges = [entry for entry in trace if entry["tool"] == "branch_merge"]
    assert len(previews) == 3
    assert len(merges) == 3
    assert previews[0]["payload"]["result"]["mergeable"] is True
    assert merges[0]["payload"]["result"]["preview_enforced"] is True
    assert merges[1]["payload"]["error"]["code"] == "STALE_MERGE_PREVIEW"
    assert previews[2]["payload"]["result"]["mergeable"] is False
    assert merges[2]["payload"]["error"]["code"] == "MERGE_CONFLICT"
