from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[2]
DOCUMENT = "main.weave"


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


def _server_environment(tmp_path: Path, compiler: Path | None) -> dict[str, str]:
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


async def _call(
    session: ClientSession,
    trace: list[dict[str, Any]],
    name: str,
    arguments: dict[str, Any],
) -> Any:
    response = await session.call_tool(name, arguments=arguments)
    payload = _payload(response)
    trace.append({"tool": name, "arguments": arguments, "payload": payload})
    assert _attribute(response, "is_error", "isError") is not True, payload
    assert payload.get("ok") is True, payload
    return payload.get("result")


def _constant_batch(root_id: str, value: int = 42) -> list[dict[str, Any]]:
    return [
        {"op": "create_form", "parent": root_id, "head": "entry", "as": "entry"},
        {
            "op": "add_atom",
            "parent": "@entry",
            "kind": "symbol",
            "value": "main",
        },
        {"op": "create_form", "parent": "@entry", "head": "params"},
        {"op": "create_form", "parent": "@entry", "head": "returns", "as": "returns"},
        {
            "op": "add_atom",
            "parent": "@returns",
            "kind": "symbol",
            "value": "i32",
        },
        {"op": "create_form", "parent": "@entry", "head": "do", "as": "body"},
        {"op": "create_form", "parent": "@body", "head": "return", "as": "return"},
        {
            "op": "create_form",
            "parent": "@return",
            "head": "const_i32",
            "as": "constant",
        },
        {
            "op": "add_atom",
            "parent": "@constant",
            "kind": "integer",
            "value": value,
        },
    ]


def _sum80_batch(root_id: str) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = [
        {"op": "create_form", "parent": root_id, "head": "entry", "as": "entry"},
        {
            "op": "add_atom",
            "parent": "@entry",
            "kind": "symbol",
            "value": "main",
        },
        {"op": "create_form", "parent": "@entry", "head": "params"},
        {"op": "create_form", "parent": "@entry", "head": "returns", "as": "returns"},
        {
            "op": "add_atom",
            "parent": "@returns",
            "kind": "symbol",
            "value": "i32",
        },
        {"op": "create_form", "parent": "@entry", "head": "do", "as": "body"},
        {"op": "create_form", "parent": "@body", "head": "return", "as": "return"},
    ]
    next_alias = 0

    def append_sum(parent: str, count: int) -> None:
        nonlocal next_alias
        if count == 1:
            alias = f"constant_{next_alias}"
            next_alias += 1
            operations.append(
                {"op": "create_form", "parent": parent, "head": "const_i32", "as": alias}
            )
            operations.append(
                {
                    "op": "add_atom",
                    "parent": f"@{alias}",
                    "kind": "integer",
                    "value": 1,
                }
            )
            return
        alias = f"add_{next_alias}"
        next_alias += 1
        operations.append(
            {"op": "create_form", "parent": parent, "head": "add_i32", "as": alias}
        )
        left = count // 2
        append_sum(f"@{alias}", left)
        append_sum(f"@{alias}", count - left)

    append_sum("@return", 80)
    assert len(operations) == 246
    return operations


async def _run_protocol_batch(tmp_path: Path) -> None:
    trace: list[dict[str, Any]] = []
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "weave_jacquard.mcp_build"],
        env=_server_environment(tmp_path, None),
        cwd=str(ROOT),
    )
    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        assert "node_apply_batch" in {tool.name for tool in tools.tools}
        await _call(session, trace, "project_initialize", {"project": "batch-protocol"})
        created = await _call(
            session,
            trace,
            "program_create",
            {
                "project": "batch-protocol",
                "branch": "main",
                "document": DOCUMENT,
                "program_name": "batch-protocol",
            },
        )
        batch = await _call(
            session,
            trace,
            "node_apply_batch",
            {
                "project": "batch-protocol",
                "branch": "main",
                "document": DOCUMENT,
                "expected_revision_id": created["revision_id"],
                "operations": _constant_batch(created["node_id"]),
            },
        )
        assert batch["operation_count"] == 9
        assert batch["created_node_count"] == 9
        history = await _call(
            session,
            trace,
            "branch_history",
            {"project": "batch-protocol", "branch": "main", "limit": 10},
        )
        assert len(history) == 3
        rendered = await _call(
            session,
            trace,
            "program_render",
            {
                "project": "batch-protocol",
                "branch": "main",
                "document": DOCUMENT,
                "annotated": False,
            },
        )
        assert "(return (const_i32 42))" in rendered["source"]


async def _run_native_batch(tmp_path: Path, compiler: Path) -> dict[str, Any]:
    trace: list[dict[str, Any]] = []
    project = "batched-sum80"
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "weave_jacquard.mcp_build"],
        env=_server_environment(tmp_path, compiler),
        cwd=str(ROOT),
    )
    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        await _call(session, trace, "project_initialize", {"project": project})
        created = await _call(
            session,
            trace,
            "program_create",
            {
                "project": project,
                "branch": "main",
                "document": DOCUMENT,
                "program_name": project,
            },
        )
        operations = _sum80_batch(created["node_id"])
        started = time.perf_counter()
        batch = await _call(
            session,
            trace,
            "node_apply_batch",
            {
                "project": project,
                "branch": "main",
                "document": DOCUMENT,
                "expected_revision_id": created["revision_id"],
                "message": "construct balanced sum of 80 constants",
                "operations": operations,
            },
        )
        batch_duration_ms = (time.perf_counter() - started) * 1000.0
        assert batch["operation_count"] == 246
        assert batch["created_node_count"] == 246
        assert batch["node_count"] == 251

        history = await _call(
            session,
            trace,
            "branch_history",
            {"project": project, "branch": "main", "limit": 10},
        )
        assert len(history) == 3
        rendered = await _call(
            session,
            trace,
            "program_render",
            {
                "project": project,
                "branch": "main",
                "document": DOCUMENT,
                "annotated": False,
            },
        )
        source = str(rendered["source"])
        assert source.count("(add_i32") == 79
        assert source.count("(const_i32 1)") == 80

        validated = await _call(
            session,
            trace,
            "program_validate",
            {"project": project, "branch": "main", "document": DOCUMENT},
        )
        assert validated["available"] is True
        assert validated["valid"] is True
        assert validated["wir"].strip()

        built = await _call(
            session,
            trace,
            "program_build",
            {"project": project, "branch": "main", "document": DOCUMENT},
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
        materialized = Path(inspected["artifact_paths"]["source"])
        assert materialized.read_text(encoding="utf-8") == source + "\n"
        executable = Path(inspected["artifact_paths"]["executable"])
        completed = subprocess.run(
            [str(executable)],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert completed.returncode == 80

    wir = tmp_path / "program.wir"
    llvm = tmp_path / "program.ll"
    bitcode = tmp_path / "program.bc"
    subprocess.run(
        [str(compiler), "--frontend", str(wir), str(materialized)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    subprocess.run(
        [str(compiler), "--backend", str(wir), str(llvm)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    subprocess.run(
        ["llvm-as", str(llvm), "-o", str(bitcode)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    llvm_text = llvm.read_text(encoding="utf-8")
    assert "define i32 @main" in llvm_text
    assert "add i32" in llvm_text

    summary = {
        "case": project,
        "actual_exit": completed.returncode,
        "structural_operation_count": 246,
        "batch_write_calls": 1,
        "atomic_write_calls_equivalent": 246,
        "write_call_reduction_ratio": 1.0 - (1.0 / 246.0),
        "reachable_revision_count": 3,
        "atomic_revision_count_equivalent": 248,
        "revision_reduction_ratio": 1.0 - (3.0 / 248.0),
        "mcp_call_count": len(trace),
        "batch_duration_ms": batch_duration_ms,
        "source_bytes": materialized.stat().st_size,
        "wir_bytes": wir.stat().st_size,
        "llvm_bytes": llvm.stat().st_size,
        "bitcode_bytes": bitcode.stat().st_size,
        "build_id": inspected["build_id"],
    }
    (tmp_path / "qualification-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "qualification-trace.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


@pytest.mark.real_mcp
def test_real_stdio_mcp_batch_commits_one_revision(tmp_path: Path) -> None:
    asyncio.run(_run_protocol_batch(tmp_path))


@pytest.mark.real_mcp
@pytest.mark.real_e2e
def test_real_stdio_mcp_batch_reduces_round_trips_and_runs(tmp_path: Path) -> None:
    configured = os.environ.get("WEAVEC_BIN")
    if not configured:
        pytest.skip("set WEAVEC_BIN to an executable final weavec")
    compiler = Path(configured).expanduser().resolve()
    if not compiler.is_file() or not os.access(compiler, os.X_OK):
        pytest.skip(f"WEAVEC_BIN is not executable: {compiler}")
    if os.name == "nt":
        pytest.skip("native execution qualification is currently POSIX-only")

    summary = asyncio.run(_run_native_batch(tmp_path, compiler))
    assert summary["write_call_reduction_ratio"] > 0.99
    assert summary["revision_reduction_ratio"] > 0.98
