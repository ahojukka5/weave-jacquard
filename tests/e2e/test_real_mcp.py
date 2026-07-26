from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_TOOLS = {
    "project_initialize",
    "program_create",
    "program_render",
    "program_validate",
    "program_build",
    "build_get",
    "node_create_form",
    "node_add_atom",
    "node_inspect",
    "branch_history",
}


def _server_environment(tmp_path: Path, compiler: Path | None = None) -> dict[str, str]:
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
    environment.pop("WEAVEC_SOURCE_ROOT", None)
    if compiler is None:
        environment.pop("WEAVEC_BIN", None)
    else:
        environment["WEAVEC_BIN"] = str(compiler)
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


async def _call(
    session: ClientSession,
    trace: list[dict[str, Any]],
    name: str,
    arguments: dict[str, Any],
) -> Any:
    result = await session.call_tool(name, arguments=arguments)
    payload = _payload(result)
    trace.append({"tool": name, "arguments": arguments, "payload": payload})
    assert _attribute(result, "is_error", "isError") is not True, payload
    assert payload.get("ok") is True, payload
    return payload.get("result")


async def _form(
    session: ClientSession,
    trace: list[dict[str, Any]],
    *,
    project: str,
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
            "branch": "main",
            "document": document,
            "parent_id": parent_id,
            "head": head,
        },
    )


async def _atom(
    session: ClientSession,
    trace: list[dict[str, Any]],
    *,
    project: str,
    document: str,
    parent_id: str,
    kind: str,
    value: Any,
) -> dict[str, Any]:
    return await _call(
        session,
        trace,
        "node_add_atom",
        {
            "project": project,
            "branch": "main",
            "document": document,
            "parent_id": parent_id,
            "kind": kind,
            "value": value,
        },
    )


async def _construct_constant_program(
    session: ClientSession,
    trace: list[dict[str, Any]],
    *,
    project: str,
    document: str,
) -> str:
    await _call(session, trace, "project_initialize", {"project": project})
    created = await _call(
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
    root_id = str(created["node_id"])

    entry = await _form(
        session,
        trace,
        project=project,
        document=document,
        parent_id=root_id,
        head="entry",
    )
    entry_id = str(entry["node_id"])
    await _atom(
        session,
        trace,
        project=project,
        document=document,
        parent_id=entry_id,
        kind="symbol",
        value="main",
    )
    await _form(
        session,
        trace,
        project=project,
        document=document,
        parent_id=entry_id,
        head="params",
    )
    returns = await _form(
        session,
        trace,
        project=project,
        document=document,
        parent_id=entry_id,
        head="returns",
    )
    await _atom(
        session,
        trace,
        project=project,
        document=document,
        parent_id=str(returns["node_id"]),
        kind="symbol",
        value="i32",
    )
    body = await _form(
        session,
        trace,
        project=project,
        document=document,
        parent_id=entry_id,
        head="do",
    )
    returned = await _form(
        session,
        trace,
        project=project,
        document=document,
        parent_id=str(body["node_id"]),
        head="return",
    )
    constant = await _form(
        session,
        trace,
        project=project,
        document=document,
        parent_id=str(returned["node_id"]),
        head="const_i32",
    )
    await _atom(
        session,
        trace,
        project=project,
        document=document,
        parent_id=str(constant["node_id"]),
        kind="integer",
        value=42,
    )

    rendered = await _call(
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
    source = str(rendered["source"])
    assert "(entry main" in source
    assert "(params)" in source
    assert "(returns i32)" in source
    assert "(return (const_i32 42))" in source
    assert "@n_" not in source
    return source


async def _run_stdio_qualification(
    tmp_path: Path,
    *,
    compiler: Path | None,
    build_native: bool,
) -> list[dict[str, Any]]:
    trace: list[dict[str, Any]] = []
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "weave_jacquard.mcp_build"],
        env=_server_environment(tmp_path, compiler),
        cwd=str(ROOT),
    )

    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            initialized = await session.initialize()
            server_info = _attribute(initialized, "server_info", "serverInfo")
            assert server_info is not None
            assert server_info.name == "weave-mcp"

            listed = await session.list_tools()
            names = {tool.name for tool in listed.tools}
            assert EXPECTED_TOOLS <= names

            source = await _construct_constant_program(
                session,
                trace,
                project="stdio-qualification",
                document="main.weave",
            )
            history = await _call(
                session,
                trace,
                "branch_history",
                {"project": "stdio-qualification", "branch": "main"},
            )
            assert len(history) >= 10

            if build_native:
                validated = await _call(
                    session,
                    trace,
                    "program_validate",
                    {
                        "project": "stdio-qualification",
                        "branch": "main",
                        "document": "main.weave",
                    },
                )
                assert validated["available"] is True
                assert validated["valid"] is True
                assert isinstance(validated["wir"], str)
                assert validated["wir"].strip()

                built = await _call(
                    session,
                    trace,
                    "program_build",
                    {
                        "project": "stdio-qualification",
                        "branch": "main",
                        "document": "main.weave",
                    },
                )
                assert built["status"] == "succeeded"
                assert built["compiler_manifest_protocol_valid"] is True
                assert built["compiler_diagnostics_protocol_valid"] is True

                inspected = await _call(
                    session,
                    trace,
                    "build_get",
                    {"build_id": built["build_id"]},
                )
                assert inspected["build_id"] == built["build_id"]
                materialized = Path(inspected["artifact_paths"]["source"])
                assert materialized.read_text(encoding="utf-8") == source

                executable = Path(inspected["artifact_paths"]["executable"])
                completed = subprocess.run(
                    [str(executable)],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                assert completed.returncode == 42

    (tmp_path / "qualification-trace.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return trace


@pytest.mark.real_mcp
def test_real_stdio_mcp_constructs_program_through_public_tools(tmp_path: Path) -> None:
    trace = asyncio.run(
        _run_stdio_qualification(tmp_path, compiler=None, build_native=False)
    )
    assert [entry["tool"] for entry in trace].count("node_create_form") == 6
    assert trace[-1]["tool"] == "branch_history"


@pytest.mark.real_mcp
@pytest.mark.real_e2e
def test_real_stdio_mcp_builds_and_runs_with_final_weavec(tmp_path: Path) -> None:
    configured = os.environ.get("WEAVEC_BIN")
    if not configured:
        pytest.skip("set WEAVEC_BIN to an executable final weavec")
    compiler = Path(configured).expanduser().resolve()
    if not compiler.is_file() or not os.access(compiler, os.X_OK):
        pytest.skip(f"WEAVEC_BIN is not executable: {compiler}")
    if os.name == "nt":
        pytest.skip("native execution qualification is currently POSIX-only")

    trace = asyncio.run(
        _run_stdio_qualification(tmp_path, compiler=compiler, build_native=True)
    )
    assert any(entry["tool"] == "program_validate" for entry in trace)
    assert any(entry["tool"] == "program_build" for entry in trace)
    assert any(entry["tool"] == "build_get" for entry in trace)
