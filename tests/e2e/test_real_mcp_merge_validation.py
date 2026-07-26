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
DOCUMENT = "main.weave"
PROJECT = "validated-merge"
TARGET = "application"


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


async def _call_error(
    session: ClientSession,
    trace: list[dict[str, Any]],
    tool_name: str,
    **arguments: Any,
) -> dict[str, Any]:
    response = await session.call_tool(tool_name, arguments=arguments)
    payload = _payload(response)
    trace.append({"tool": tool_name, "arguments": arguments, "payload": payload})
    assert payload.get("ok") is False, payload
    error = payload.get("error")
    assert isinstance(error, dict)
    return error


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


def _form(parent: str, head: str, alias: str | None = None) -> dict[str, Any]:
    operation: dict[str, Any] = {"op": "create_form", "parent": parent, "head": head}
    if alias is not None:
        operation["as"] = alias
    return operation


def _atom(
    parent: str,
    kind: str,
    value: Any,
    alias: str | None = None,
) -> dict[str, Any]:
    operation: dict[str, Any] = {
        "op": "add_atom",
        "parent": parent,
        "kind": kind,
        "value": value,
    }
    if alias is not None:
        operation["as"] = alias
    return operation


def _function_returning_constant(
    root_id: str,
    name: str,
    value: int,
    prefix: str,
) -> list[dict[str, Any]]:
    return [
        _form(root_id, "fn", f"{prefix}_fn"),
        _atom(f"@{prefix}_fn", "symbol", name),
        _form(f"@{prefix}_fn", "params"),
        _form(f"@{prefix}_fn", "returns", f"{prefix}_returns"),
        _atom(f"@{prefix}_returns", "symbol", "i32"),
        _form(f"@{prefix}_fn", "do", f"{prefix}_body"),
        _form(f"@{prefix}_body", "return", f"{prefix}_return"),
        _form(f"@{prefix}_return", "const_i32", f"{prefix}_const"),
        _atom(f"@{prefix}_const", "integer", value, f"{prefix}_constant"),
    ]


def _program_operations(root_id: str) -> list[dict[str, Any]]:
    operations = [
        _form(root_id, "entry", "entry"),
        _atom("@entry", "symbol", "main"),
    ]
    operations.extend(_function_returning_constant(root_id, "target_value", 1, "target"))
    operations.extend(_function_returning_constant(root_id, "source_value", 2, "source"))
    operations.extend(
        [
            _form(root_id, "fn", "main_fn"),
            _atom("@main_fn", "symbol", "main"),
            _form("@main_fn", "params"),
            _form("@main_fn", "returns", "main_returns"),
            _atom("@main_returns", "symbol", "i32"),
            _form("@main_fn", "do", "main_body"),
            _form("@main_body", "return", "main_return"),
            _form("@main_return", "add_i32", "sum"),
            _form("@sum", "call_i32", "target_call"),
            _atom("@target_call", "symbol", "target_value"),
            _form("@sum", "call_i32", "source_call"),
            _atom("@source_call", "symbol", "source_value"),
        ]
    )
    return operations


async def _run(tmp_path: Path, compiler: Path) -> list[dict[str, Any]]:
    trace: list[dict[str, Any]] = []
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "weave_jacquard.mcp_build"],
        env=_environment(tmp_path, compiler),
        cwd=str(ROOT),
    )
    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        names = {tool.name for tool in tools.tools}
        assert {"branch_merge_preview", "branch_merge_validate", "branch_merge"} <= names

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
        batch = await _call(
            session,
            trace,
            "node_apply_batch",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            expected_revision_id=created["revision_id"],
            operations=_program_operations(created["node_id"]),
            message="construct independently editable merge-validation program",
        )
        aliases = batch["aliases"]
        await _call(
            session,
            trace,
            "build_target_set",
            project=PROJECT,
            branch="main",
            name=TARGET,
            document=DOCUMENT,
        )
        await _call(
            session,
            trace,
            "build_target_validate",
            project=PROJECT,
            branch="main",
            name=TARGET,
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
            document=DOCUMENT,
            node_id=aliases["target_constant"],
            value=10,
        )
        source_edit = await _call(
            session,
            trace,
            "node_set_atom",
            project=PROJECT,
            branch="source",
            document=DOCUMENT,
            node_id=aliases["source_constant"],
            value=20,
        )

        preview = await _call(
            session,
            trace,
            "branch_merge_preview",
            project=PROJECT,
            target_branch="target",
            source_branch="source",
        )
        assert preview["mergeable"] is True
        heads_before = await _call(session, trace, "branch_list", project=PROJECT)
        before = {item["name"]: item["head_revision_id"] for item in heads_before}
        assert before["target"] == target_edit["revision_id"]
        assert before["source"] == source_edit["revision_id"]

        validation = await _call(
            session,
            trace,
            "branch_merge_validate",
            project=PROJECT,
            target_branch="target",
            source_branch="source",
            build_target=TARGET,
            preview_id=preview["preview_id"],
        )
        assert validation["available"] is True
        assert validation["valid"] is True
        assert validation["returncode"] == 0
        assert validation["documents"] == [DOCUMENT]
        assert validation["wir_bytes"] > 0
        assert validation["compiler"]["sha256"]
        assert validation["preview_id"] == preview["preview_id"]

        heads_after_validation = await _call(
            session, trace, "branch_list", project=PROJECT
        )
        after_validation = {
            item["name"]: item["head_revision_id"] for item in heads_after_validation
        }
        assert after_validation == before

        merged = await _call(
            session,
            trace,
            "branch_merge",
            project=PROJECT,
            target_branch="target",
            source_branch="source",
            preview_id=preview["preview_id"],
            validation_target=TARGET,
        )
        assert merged["preview_enforced"] is True
        assert merged["validation_enforced"] is True
        assert merged["validation_target"] == TARGET
        assert merged["merge_validation"]["validation_id"] == validation["validation_id"]
        assert merged["merge_validation"]["valid"] is True

        validated_target = await _call(
            session,
            trace,
            "build_target_validate",
            project=PROJECT,
            branch="target",
            name=TARGET,
        )
        assert validated_target["valid"] is True
        built = await _call(
            session,
            trace,
            "build_target_build",
            project=PROJECT,
            branch="target",
            name=TARGET,
        )
        assert built["status"] == "succeeded"
        inspected = await _call(
            session,
            trace,
            "build_get",
            build_id=built["build_id"],
        )
        executable = Path(inspected["artifact_paths"]["executable"])
        completed = subprocess.run(
            [str(executable)],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert completed.returncode == 30

        await _call(
            session,
            trace,
            "branch_create",
            project=PROJECT,
            branch="broken",
            from_branch="target",
        )
        broken_qgate = await _call(
            session,
            trace,
            "node_create_form",
            project=PROJECT,
            branch="broken",
            document=DOCUMENT,
            parent_id=aliases["main_body"],
            head="qgate",
        )
        await _call(
            session,
            trace,
            "node_add_atom",
            project=PROJECT,
            branch="broken",
            document=DOCUMENT,
            parent_id=broken_qgate["node_id"],
            kind="symbol",
            value="H",
        )
        broken_preview = await _call(
            session,
            trace,
            "branch_merge_preview",
            project=PROJECT,
            target_branch="target",
            source_branch="broken",
        )
        broken_validation = await _call(
            session,
            trace,
            "branch_merge_validate",
            project=PROJECT,
            target_branch="target",
            source_branch="broken",
            build_target=TARGET,
            preview_id=broken_preview["preview_id"],
        )
        assert broken_validation["available"] is True
        assert broken_validation["valid"] is False
        target_before_rejection = merged["revision_id"]
        rejection = await _call_error(
            session,
            trace,
            "branch_merge",
            project=PROJECT,
            target_branch="target",
            source_branch="broken",
            preview_id=broken_preview["preview_id"],
            validation_target=TARGET,
        )
        assert rejection["code"] == "MERGE_VALIDATION_FAILED"
        final_branches = await _call(session, trace, "branch_list", project=PROJECT)
        final_heads = {
            item["name"]: item["head_revision_id"] for item in final_branches
        }
        assert final_heads["target"] == target_before_rejection

    (tmp_path / "merge-validation-trace.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return trace


@pytest.mark.real_mcp
@pytest.mark.real_e2e
def test_real_mcp_validates_and_executes_exact_merge_candidate(tmp_path: Path) -> None:
    configured = os.environ.get("WEAVEC_BIN")
    if not configured:
        pytest.skip("WEAVEC_BIN is required for merge candidate qualification")
    compiler = Path(configured).resolve()
    assert compiler.is_file()
    trace = asyncio.run(_run(tmp_path, compiler))
    validations = [entry for entry in trace if entry["tool"] == "branch_merge_validate"]
    merges = [entry for entry in trace if entry["tool"] == "branch_merge"]
    assert len(validations) == 2
    assert validations[0]["payload"]["result"]["valid"] is True
    assert validations[1]["payload"]["result"]["valid"] is False
    assert merges[0]["payload"]["result"]["validation_enforced"] is True
    assert merges[1]["payload"]["error"]["code"] == "MERGE_VALIDATION_FAILED"
