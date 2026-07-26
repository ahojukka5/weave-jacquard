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
PROJECT = "compiler-guided-repair"
DOCUMENT = "main.weave"
CASE = "compiler-guided-repair"


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


def _invalid_program_operations(root_id: str) -> list[dict[str, Any]]:
    return [
        _form(root_id, "entry", "entry"),
        _atom("@entry", "symbol", "main"),
        _form("@entry", "params"),
        _form("@entry", "returns", "returns"),
        _atom("@returns", "symbol", "i32"),
        _form("@entry", "do", "body"),
        _form("@body", "return", "return"),
        _form("@return", "unknown_form", "invalid"),
        _atom("@invalid", "integer", 0),
    ]


def _read_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _replay_compiler(tmp_path: Path, compiler: Path, source: Path) -> dict[str, int]:
    wir = tmp_path / "program.wir"
    llvm = tmp_path / "program.ll"
    bitcode = tmp_path / "program.bc"
    subprocess.run(
        [str(compiler), "--frontend", str(wir), str(source)],
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
        "wir_bytes": wir.stat().st_size,
        "llvm_bytes": llvm.stat().st_size,
        "bitcode_bytes": bitcode.stat().st_size,
    }


async def _run(tmp_path: Path, compiler: Path) -> dict[str, Any]:
    trace: list[dict[str, Any]] = []
    async with (
        stdio_client(_parameters(tmp_path, compiler)) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        listed = await session.list_tools()
        names = {tool.name for tool in listed.tools}
        assert {
            "node_apply_batch",
            "node_find",
            "node_set_atom",
            "program_validate",
            "program_build",
            "build_get",
            "branch_activity_summary",
        } <= names

        await _call(session, trace, "project_initialize", project=PROJECT)
        created = await _call(
            session,
            trace,
            "program_create",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            program_name=PROJECT,
        )
        operations = _invalid_program_operations(created["node_id"])
        invalid = await _call(
            session,
            trace,
            "node_apply_batch",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            expected_revision_id=created["revision_id"],
            message="construct program with one unknown expression operator",
            operations=operations,
        )
        assert invalid["operation_count"] == 9

        matches = await _call(
            session,
            trace,
            "node_find",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            kind="symbol",
            value="unknown_form",
        )
        assert len(matches) == 1
        invalid_node_id = str(matches[0]["node_id"])

        frontend = await _call(
            session,
            trace,
            "program_validate",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
        )
        assert frontend["available"] is True
        assert frontend["valid"] is True
        assert "unknown_form" in str(frontend["wir"])

        before_failure = await _call(
            session,
            trace,
            "branch_activity_summary",
            project=PROJECT,
            branch="main",
        )
        failed = await _call(
            session,
            trace,
            "program_build",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
        )
        assert failed["status"] == "failed"
        assert failed["returncode"] == 11
        assert failed["compiler_manifest_protocol_valid"] is True
        assert failed["compiler_diagnostics_protocol_valid"] is True
        assert failed["artifact_paths"]["executable"] is None
        assert failed["revision_id"] == invalid["revision_id"]

        failed_build = await _call(
            session,
            trace,
            "build_get",
            build_id=failed["build_id"],
        )
        failed_diagnostics = _read_json(failed_build["artifact_paths"]["diagnostics"])
        assert failed_diagnostics["protocol_valid"] is True
        assert len(failed_diagnostics["entries"]) == 1
        diagnostic = failed_diagnostics["entries"][0]
        assert diagnostic["code"] == "backend.unknown-expression-operator"
        assert diagnostic["node_id"] == invalid_node_id
        assert diagnostic["document"] == DOCUMENT
        assert diagnostic["span_origin"] == "inferred-unique-token"

        after_failure = await _call(
            session,
            trace,
            "branch_activity_summary",
            project=PROJECT,
            branch="main",
        )
        assert after_failure["head_revision_id"] == before_failure["head_revision_id"]
        assert after_failure["revision_count"] == before_failure["revision_count"]
        assert after_failure["operation_count"] == before_failure["operation_count"]

        repaired = await _call(
            session,
            trace,
            "node_set_atom",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            node_id=invalid_node_id,
            value="const_i32",
        )
        assert repaired["node_id"] == invalid_node_id
        assert repaired["revision_id"] != invalid["revision_id"]

        remaining = await _call(
            session,
            trace,
            "node_find",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            kind="symbol",
            value="unknown_form",
        )
        assert remaining == []
        repaired_matches = await _call(
            session,
            trace,
            "node_find",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            kind="symbol",
            value="const_i32",
        )
        assert [str(item["node_id"]) for item in repaired_matches] == [invalid_node_id]

        validated = await _call(
            session,
            trace,
            "program_validate",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
        )
        assert validated["available"] is True
        assert validated["valid"] is True

        succeeded = await _call(
            session,
            trace,
            "program_build",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
        )
        assert succeeded["status"] == "succeeded"
        assert succeeded["revision_id"] == repaired["revision_id"]
        assert succeeded["build_id"] != failed["build_id"]
        successful_build = await _call(
            session,
            trace,
            "build_get",
            build_id=succeeded["build_id"],
        )
        source = Path(successful_build["artifact_paths"]["source"])
        source_text = source.read_text(encoding="utf-8")
        assert "unknown_form" not in source_text
        assert "(const_i32 0)" in source_text
        executable = Path(successful_build["artifact_paths"]["executable"])
        completed = subprocess.run(
            [str(executable)],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert completed.returncode == 0

        failed_again = await _call(
            session,
            trace,
            "build_get",
            build_id=failed["build_id"],
        )
        assert failed_again["build_id"] == failed_build["build_id"]
        assert failed_again["status"] == "failed"
        assert _read_json(failed_again["artifact_paths"]["diagnostics"]) == failed_diagnostics

        final_activity = await _call(
            session,
            trace,
            "branch_activity_summary",
            project=PROJECT,
            branch="main",
        )
        assert final_activity["revision_count"] == before_failure["revision_count"] + 1
        assert final_activity["operation_count"] == before_failure["operation_count"] + 1

    compiler_sizes = _replay_compiler(tmp_path, compiler, source)
    summary = {
        "case": CASE,
        "actual_exit": completed.returncode,
        "failed_build_id": failed["build_id"],
        "successful_build_id": succeeded["build_id"],
        "failed_revision_id": invalid["revision_id"],
        "successful_revision_id": repaired["revision_id"],
        "diagnostic_code": diagnostic["code"],
        "diagnostic_node_id": diagnostic["node_id"],
        "repaired_node_id": invalid_node_id,
        "failed_build_retained": True,
        "failed_build_published_executable": False,
        "repair_revision_delta": 1,
        "mcp_call_count": len(trace),
        "source_bytes": source.stat().st_size,
        **compiler_sizes,
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
@pytest.mark.real_e2e
def test_real_mcp_compiler_diagnostic_guides_stable_node_repair(tmp_path: Path) -> None:
    configured = os.environ.get("WEAVEC_BIN")
    if not configured:
        pytest.skip("set WEAVEC_BIN to an executable final weavec")
    compiler = Path(configured).expanduser().resolve()
    if not compiler.is_file() or not os.access(compiler, os.X_OK):
        pytest.skip(f"WEAVEC_BIN is not executable: {compiler}")
    if os.name == "nt":
        pytest.skip("native execution qualification is currently POSIX-only")

    summary = asyncio.run(_run(tmp_path, compiler))
    assert summary["diagnostic_node_id"] == summary["repaired_node_id"]
    assert summary["failed_build_retained"] is True
