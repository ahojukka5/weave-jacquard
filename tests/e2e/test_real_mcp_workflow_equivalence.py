from __future__ import annotations

import asyncio
import hashlib
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
DOCUMENT = "main.weave"
CASE = "atomic-batch-equivalence-sum32"
PROGRAM_NAME = "workflow-equivalence"


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


def _environment(tmp_path: Path, compiler: Path) -> dict[str, str]:
    environment = os.environ.copy()
    python_path = str(ROOT / "src")
    if environment.get("PYTHONPATH"):
        python_path += os.pathsep + environment["PYTHONPATH"]
    environment.update(
        {
            "PYTHONPATH": python_path,
            "WEAVE_DB_PATH": str(tmp_path / "jacquard.db"),
            "WEAVE_BUILD_ROOT": str(tmp_path / "builds"),
            "WEAVEC_BIN": str(compiler),
        }
    )
    environment.pop("WEAVEC_SOURCE_ROOT", None)
    return environment


def _parameters(tmp_path: Path, compiler: Path) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "weave_jacquard.mcp_build"],
        env=_environment(tmp_path, compiler),
        cwd=str(ROOT),
    )


def _form(parent: str, head: str, alias: str | None = None) -> dict[str, Any]:
    operation: dict[str, Any] = {"op": "create_form", "parent": parent, "head": head}
    if alias is not None:
        operation["as"] = alias
    return operation


def _atom(parent: str, kind: str, value: Any) -> dict[str, Any]:
    return {"op": "add_atom", "parent": parent, "kind": kind, "value": value}


def _entry_prefix(root_id: str) -> list[dict[str, Any]]:
    return [
        _form(root_id, "entry", "entry"),
        _atom("@entry", "symbol", "main"),
        _form("@entry", "params"),
        _form("@entry", "returns", "returns"),
        _atom("@returns", "symbol", "i32"),
        _form("@entry", "do", "body"),
        _form("@body", "return", "return"),
    ]


def _sum32_operations(root_id: str) -> list[dict[str, Any]]:
    operations = _entry_prefix(root_id)
    next_alias = 0

    def append_sum(parent: str, count: int) -> None:
        nonlocal next_alias
        alias = f"node_{next_alias}"
        next_alias += 1
        if count == 1:
            operations.extend([_form(parent, "const_i32", alias), _atom(f"@{alias}", "integer", 1)])
            return
        operations.append(_form(parent, "add_i32", alias))
        left = count // 2
        append_sum(f"@{alias}", left)
        append_sum(f"@{alias}", count - left)

    append_sum("@return", 32)
    assert len(operations) == 102
    return operations


def _resolve(reference: str, aliases: dict[str, str]) -> str:
    if reference.startswith("@"):
        return aliases[reference[1:]]
    return reference


async def _create_program(
    session: ClientSession,
    trace: list[dict[str, Any]],
    project: str,
) -> dict[str, Any]:
    await _call(session, trace, "project_initialize", project=project)
    return await _call(
        session,
        trace,
        "program_create",
        project=project,
        branch="main",
        document=DOCUMENT,
        program_name=PROGRAM_NAME,
    )


async def _apply_atomic(
    session: ClientSession,
    trace: list[dict[str, Any]],
    project: str,
    operations: list[dict[str, Any]],
) -> None:
    aliases: dict[str, str] = {}
    for operation in operations:
        parent = _resolve(str(operation["parent"]), aliases)
        if operation["op"] == "create_form":
            result = await _call(
                session,
                trace,
                "node_create_form",
                project=project,
                branch="main",
                document=DOCUMENT,
                parent_id=parent,
                head=operation["head"],
            )
            alias = operation.get("as")
            if alias is not None:
                aliases[str(alias)] = str(result["node_id"])
            continue
        assert operation["op"] == "add_atom"
        await _call(
            session,
            trace,
            "node_add_atom",
            project=project,
            branch="main",
            document=DOCUMENT,
            parent_id=parent,
            kind=operation["kind"],
            value=operation["value"],
        )


async def _qualify_project(
    session: ClientSession,
    trace: list[dict[str, Any]],
    project: str,
) -> dict[str, Any]:
    rendered = await _call(
        session,
        trace,
        "program_render",
        project=project,
        branch="main",
        document=DOCUMENT,
        annotated=False,
    )
    source = str(rendered["source"])
    assert source.count("(add_i32") == 31
    assert source.count("(const_i32 1)") == 32

    validated = await _call(
        session,
        trace,
        "program_validate",
        project=project,
        branch="main",
        document=DOCUMENT,
    )
    assert validated["valid"] is True

    built = await _call(
        session,
        trace,
        "program_build",
        project=project,
        branch="main",
        document=DOCUMENT,
    )
    assert built["status"] == "succeeded"
    inspected = await _call(
        session,
        trace,
        "build_get",
        build_id=built["build_id"],
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
    assert completed.returncode == 32

    activity = await _call(
        session,
        trace,
        "branch_activity_summary",
        project=project,
        branch="main",
    )
    return {
        "source": source,
        "build_id": inspected["build_id"],
        "exit": completed.returncode,
        "activity": activity,
    }


def _replay_compiler(
    root: Path,
    compiler: Path,
    source: str,
) -> dict[str, bytes]:
    root.mkdir(parents=True, exist_ok=True)
    source_path = root / "input.weave"
    wir = root / "program.wir"
    llvm = root / "program.ll"
    bitcode = root / "program.bc"
    source_path.write_text(source + "\n", encoding="utf-8")
    for output in (wir, llvm, bitcode):
        output.unlink(missing_ok=True)
    subprocess.run(
        [str(compiler), "--frontend", str(wir), str(source_path)],
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
    return {
        "wir": wir.read_bytes(),
        "llvm": llvm.read_bytes(),
        "bitcode": bitcode.read_bytes(),
    }


async def _run(tmp_path: Path, compiler: Path) -> dict[str, Any]:
    atomic_trace: list[dict[str, Any]] = []
    batch_trace: list[dict[str, Any]] = []
    async with (
        stdio_client(_parameters(tmp_path, compiler)) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        listed = await session.list_tools()
        names = {tool.name for tool in listed.tools}
        assert {"node_apply_batch", "branch_activity_summary"} <= names

        atomic_created = await _create_program(session, atomic_trace, "atomic-equivalence")
        atomic_operations = _sum32_operations(atomic_created["node_id"])
        await _apply_atomic(
            session,
            atomic_trace,
            "atomic-equivalence",
            atomic_operations,
        )
        atomic = await _qualify_project(
            session,
            atomic_trace,
            "atomic-equivalence",
        )

        batch_created = await _create_program(session, batch_trace, "batch-equivalence")
        batch_operations = _sum32_operations(batch_created["node_id"])
        batch = await _call(
            session,
            batch_trace,
            "node_apply_batch",
            project="batch-equivalence",
            branch="main",
            document=DOCUMENT,
            expected_revision_id=batch_created["revision_id"],
            message="construct balanced sum of 32 constants",
            operations=batch_operations,
        )
        assert batch["operation_count"] == len(batch_operations)
        batched = await _qualify_project(
            session,
            batch_trace,
            "batch-equivalence",
        )

    assert atomic["source"] == batched["source"]
    assert atomic["exit"] == batched["exit"] == 32
    atomic_activity = atomic["activity"]
    batch_activity = batched["activity"]
    assert atomic_activity["operation_count"] == batch_activity["operation_count"]
    assert atomic_activity["max_operations_per_revision"] == 1
    assert batch_activity["max_operations_per_revision"] == len(batch_operations)
    assert atomic_activity["revision_count_avoided_by_grouping"] == 0
    assert batch_activity["revision_count_avoided_by_grouping"] == len(batch_operations) - 1

    replay_root = tmp_path / "compiler-replay"
    atomic_outputs = _replay_compiler(replay_root, compiler, atomic["source"])
    batched_outputs = _replay_compiler(replay_root, compiler, batched["source"])
    assert atomic_outputs == batched_outputs

    atomic_revisions = int(atomic_activity["revision_count"])
    batch_revisions = int(batch_activity["revision_count"])
    summary = {
        "case": CASE,
        "actual_exit": atomic["exit"],
        "structural_operation_count": len(atomic_operations),
        "atomic_write_calls": len(atomic_operations),
        "batch_write_calls": 1,
        "write_call_reduction_ratio": 1.0 - (1.0 / len(atomic_operations)),
        "atomic_revision_count": atomic_revisions,
        "batch_revision_count": batch_revisions,
        "revision_reduction_ratio": 1.0 - (batch_revisions / atomic_revisions),
        "atomic_mcp_call_count": len(atomic_trace),
        "batch_mcp_call_count": len(batch_trace),
        "source_identical": True,
        "wir_identical": True,
        "llvm_identical": True,
        "bitcode_identical": True,
        "source_sha256": hashlib.sha256(atomic["source"].encode()).hexdigest(),
        "source_bytes": len((atomic["source"] + "\n").encode()),
        "wir_bytes": len(atomic_outputs["wir"]),
        "llvm_bytes": len(atomic_outputs["llvm"]),
        "bitcode_bytes": len(atomic_outputs["bitcode"]),
        "atomic_build_id": atomic["build_id"],
        "batch_build_id": batched["build_id"],
    }
    (tmp_path / "qualification-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "atomic-trace.json").write_text(
        json.dumps(atomic_trace, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "batch-trace.json").write_text(
        json.dumps(batch_trace, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


@pytest.mark.real_mcp
@pytest.mark.real_e2e
def test_atomic_and_batched_workflows_are_compiler_equivalent(tmp_path: Path) -> None:
    configured = os.environ.get("WEAVEC_BIN")
    if not configured:
        pytest.skip("set WEAVEC_BIN to an executable final weavec")
    compiler = Path(configured).expanduser().resolve()
    if not compiler.is_file() or not os.access(compiler, os.X_OK):
        pytest.skip(f"WEAVEC_BIN is not executable: {compiler}")
    if os.name == "nt":
        pytest.skip("native execution qualification is currently POSIX-only")

    summary = asyncio.run(_run(tmp_path, compiler))
    assert summary["write_call_reduction_ratio"] > 0.99
    assert summary["revision_reduction_ratio"] > 0.95
