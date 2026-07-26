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
REQUIRED_TOOLS = {
    "branch_create",
    "branch_history",
    "branch_merge",
    "build_target_get",
    "build_target_list",
    "build_target_set",
    "node_add_atom",
    "node_create_form",
    "node_move",
    "program_create",
    "program_render",
    "program_source_list",
    "project_initialize",
}


def _server_environment(tmp_path: Path) -> dict[str, str]:
    environment = os.environ.copy()
    python_path = str(ROOT / "src")
    if environment.get("PYTHONPATH"):
        python_path += os.pathsep + environment["PYTHONPATH"]
    environment.update(
        {
            "PYTHONPATH": python_path,
            "WEAVE_DB_PATH": str(tmp_path / "agent-workflows.db"),
            "WEAVE_BUILD_ROOT": str(tmp_path / "builds"),
        }
    )
    environment.pop("WEAVEC_BIN", None)
    environment.pop("WEAVEC_SOURCE_ROOT", None)
    return environment


def _attribute(value: Any, snake_case: str, camel_case: str) -> Any:
    result = getattr(value, snake_case, None)
    return result if result is not None else getattr(value, camel_case, None)


def _payload(result: Any) -> dict[str, Any]:
    structured = _attribute(result, "structured_content", "structuredContent")
    if isinstance(structured, dict):
        return structured
    for block in getattr(result, "content", []):
        text = getattr(block, "text", None)
        if not isinstance(text, str):
            continue
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise AssertionError(f"tool result did not contain a JSON object: {result!r}")


async def _call_payload(
    session: ClientSession,
    trace: list[dict[str, Any]],
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    response = await session.call_tool(name, arguments=arguments)
    payload = _payload(response)
    trace.append({"tool": name, "arguments": arguments, "payload": payload})
    assert _attribute(response, "is_error", "isError") is not True, payload
    return payload


async def _call(
    session: ClientSession,
    trace: list[dict[str, Any]],
    name: str,
    arguments: dict[str, Any],
) -> Any:
    payload = await _call_payload(session, trace, name, arguments)
    assert payload.get("ok") is True, payload
    return payload.get("result")


async def _call_error(
    session: ClientSession,
    trace: list[dict[str, Any]],
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    payload = await _call_payload(session, trace, name, arguments)
    assert payload.get("ok") is False, payload
    error = payload.get("error")
    assert isinstance(error, dict), payload
    return error


async def _form(
    session: ClientSession,
    trace: list[dict[str, Any]],
    *,
    project: str,
    branch: str,
    document: str,
    parent_id: str,
    head: str,
) -> dict[str, Any]:
    return await _call(
        session,
        trace,
        "node_create_form",
        {
            "project": project,
            "branch": branch,
            "document": document,
            "parent_id": parent_id,
            "head": head,
        },
    )


async def _add_symbol(
    session: ClientSession,
    trace: list[dict[str, Any]],
    *,
    project: str,
    branch: str,
    document: str,
    parent_id: str,
    value: str,
) -> dict[str, Any]:
    return await _call(
        session,
        trace,
        "node_add_atom",
        {
            "project": project,
            "branch": branch,
            "document": document,
            "parent_id": parent_id,
            "kind": "symbol",
            "value": value,
        },
    )


async def _exercise_rejected_mutation(
    session: ClientSession,
    trace: list[dict[str, Any]],
) -> None:
    project = "rejected-mutation"
    document = "main.weave"
    await _call(session, trace, "project_initialize", {"project": project})
    program = await _call(
        session,
        trace,
        "program_create",
        {
            "project": project,
            "branch": "main",
            "document": document,
            "program_name": project,
        },
    )
    root_id = str(program["node_id"])
    parent = await _form(
        session,
        trace,
        project=project,
        branch="main",
        document=document,
        parent_id=root_id,
        head="fn",
    )
    child = await _form(
        session,
        trace,
        project=project,
        branch="main",
        document=document,
        parent_id=str(parent["node_id"]),
        head="do",
    )

    before = await _call(
        session,
        trace,
        "branch_history",
        {"project": project, "branch": "main"},
    )
    error = await _call_error(
        session,
        trace,
        "node_move",
        {
            "project": project,
            "branch": "main",
            "document": document,
            "node_id": parent["node_id"],
            "new_parent_id": child["node_id"],
        },
    )
    assert error["code"] == "MOVE_CYCLE"

    after = await _call(
        session,
        trace,
        "branch_history",
        {"project": project, "branch": "main"},
    )
    assert [item["id"] for item in after] == [item["id"] for item in before]

    repaired = await _call(
        session,
        trace,
        "node_move",
        {
            "project": project,
            "branch": "main",
            "document": document,
            "node_id": child["node_id"],
            "new_parent_id": root_id,
        },
    )
    assert repaired["node_id"] == child["node_id"]
    repaired_history = await _call(
        session,
        trace,
        "branch_history",
        {"project": project, "branch": "main"},
    )
    assert repaired_history[0]["id"] != before[0]["id"]


async def _exercise_parallel_merge(
    session: ClientSession,
    trace: list[dict[str, Any]],
) -> None:
    project = "parallel-merge"
    document = "main.weave"
    await _call(session, trace, "project_initialize", {"project": project})
    program = await _call(
        session,
        trace,
        "program_create",
        {
            "project": project,
            "branch": "main",
            "document": document,
            "program_name": project,
        },
    )
    root_id = str(program["node_id"])
    await _call(
        session,
        trace,
        "branch_create",
        {"project": project, "branch": "agent-alpha", "from_branch": "main"},
    )
    await _call(
        session,
        trace,
        "branch_create",
        {"project": project, "branch": "agent-beta", "from_branch": "main"},
    )

    alpha = await _form(
        session,
        trace,
        project=project,
        branch="agent-alpha",
        document=document,
        parent_id=root_id,
        head="fn",
    )
    await _add_symbol(
        session,
        trace,
        project=project,
        branch="agent-alpha",
        document=document,
        parent_id=str(alpha["node_id"]),
        value="alpha",
    )
    beta = await _form(
        session,
        trace,
        project=project,
        branch="agent-beta",
        document=document,
        parent_id=root_id,
        head="fn",
    )
    await _add_symbol(
        session,
        trace,
        project=project,
        branch="agent-beta",
        document=document,
        parent_id=str(beta["node_id"]),
        value="beta",
    )

    await _call(
        session,
        trace,
        "branch_merge",
        {
            "project": project,
            "target_branch": "main",
            "source_branch": "agent-alpha",
        },
    )
    await _call(
        session,
        trace,
        "branch_merge",
        {
            "project": project,
            "target_branch": "main",
            "source_branch": "agent-beta",
        },
    )
    canonical = await _call(
        session,
        trace,
        "program_render",
        {
            "project": project,
            "branch": "main",
            "document": document,
            "annotated": False,
        },
    )
    canonical_source = str(canonical["source"])
    assert "(fn alpha)" in canonical_source
    assert "(fn beta)" in canonical_source

    annotated = await _call(
        session,
        trace,
        "program_render",
        {
            "project": project,
            "branch": "main",
            "document": document,
            "annotated": True,
            "annotate_atoms": True,
        },
    )
    annotated_source = str(annotated["source"])
    assert f"@{alpha['node_id']}" in annotated_source
    assert f"@{beta['node_id']}" in annotated_source

    history = await _call(
        session,
        trace,
        "branch_history",
        {"project": project, "branch": "main"},
    )
    assert history[0]["parent2_id"] is not None
    assert history[1]["parent2_id"] is not None


async def _exercise_revisioned_target(
    session: ClientSession,
    trace: list[dict[str, Any]],
) -> None:
    project = "revisioned-target"
    await _call(session, trace, "project_initialize", {"project": project})
    for document in ("main.weave", "library.weave", "platform.weave"):
        await _call(
            session,
            trace,
            "program_create",
            {
                "project": project,
                "branch": "main",
                "document": document,
                "program_name": document.removesuffix(".weave"),
            },
        )

    target = await _call(
        session,
        trace,
        "build_target_set",
        {
            "project": project,
            "name": "application",
            "document": "main.weave",
            "branch": "main",
            "additional_documents": ["platform.weave", "library.weave"],
        },
    )
    target_revision = str(target["revision_id"])
    assert target["additional_documents"] == ["platform.weave", "library.weave"]
    assert target["compiler_target"] == "native"

    exact = await _call(
        session,
        trace,
        "build_target_get",
        {
            "project": project,
            "name": "application",
            "branch": "main",
            "revision_id": target_revision,
        },
    )
    assert exact["revision_id"] == target_revision
    assert exact["additional_documents"] == ["platform.weave", "library.weave"]

    listed = await _call(
        session,
        trace,
        "build_target_list",
        {"project": project, "branch": "main", "revision_id": target_revision},
    )
    assert [item["name"] for item in listed] == ["application"]

    historic_sources = await _call(
        session,
        trace,
        "program_source_list",
        {"project": project, "branch": "main", "revision_id": target_revision},
    )
    assert historic_sources == ["library.weave", "main.weave", "platform.weave"]

    await _call(
        session,
        trace,
        "program_create",
        {
            "project": project,
            "branch": "main",
            "document": "future.weave",
            "program_name": "future",
        },
    )
    current_sources = await _call(
        session,
        trace,
        "program_source_list",
        {"project": project, "branch": "main"},
    )
    assert current_sources == [
        "future.weave",
        "library.weave",
        "main.weave",
        "platform.weave",
    ]
    exact_again = await _call(
        session,
        trace,
        "build_target_get",
        {
            "project": project,
            "name": "application",
            "branch": "main",
            "revision_id": target_revision,
        },
    )
    assert exact_again == exact


async def _run_agent_workflows(tmp_path: Path) -> list[dict[str, Any]]:
    trace: list[dict[str, Any]] = []
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "weave_jacquard.mcp_build"],
        env=_server_environment(tmp_path),
        cwd=str(ROOT),
    )
    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        initialized = await session.initialize()
        server_info = _attribute(initialized, "server_info", "serverInfo")
        assert server_info is not None
        assert server_info.name == "weave-mcp"
        listed = await session.list_tools()
        names = {tool.name for tool in listed.tools}
        assert names >= REQUIRED_TOOLS

        await _exercise_rejected_mutation(session, trace)
        await _exercise_parallel_merge(session, trace)
        await _exercise_revisioned_target(session, trace)

    (tmp_path / "agent-workflow-trace.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return trace


@pytest.mark.real_mcp
def test_real_stdio_mcp_agent_workflows(tmp_path: Path) -> None:
    trace = asyncio.run(_run_agent_workflows(tmp_path))
    assert any(
        entry["tool"] == "node_move" and entry["payload"].get("ok") is False
        for entry in trace
    )
    assert [entry["tool"] for entry in trace].count("branch_merge") == 2
    assert any(entry["tool"] == "build_target_set" for entry in trace)
