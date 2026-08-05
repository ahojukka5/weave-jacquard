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
PROJECT = "merge-preflight"
DOCUMENT = "main.weave"
ORPHAN = "orphan.weave"


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


def _constant_function(
    root_id: str,
    function_name: str,
    value: int,
    prefix: str,
) -> list[dict[str, Any]]:
    return [
        _form(root_id, "fn", f"{prefix}_fn"),
        _atom(f"@{prefix}_fn", "symbol", function_name),
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
    operations.extend(_constant_function(root_id, "target_value", 1, "target"))
    operations.extend(_constant_function(root_id, "source_value", 2, "source"))
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
        assert "branch_merge_preflight" in {tool.name for tool in tools.tools}

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
            message="construct merge preflight program",
        )
        aliases = batch["aliases"]
        orphan = await _call(
            session,
            trace,
            "program_create",
            project=PROJECT,
            branch="main",
            document=ORPHAN,
            program_name="orphan",
        )
        orphan_atom = await _call(
            session,
            trace,
            "node_add_atom",
            project=PROJECT,
            branch="main",
            document=ORPHAN,
            parent_id=orphan["node_id"],
            kind="string",
            value="uncovered",
        )
        for target in ("application", "mirror"):
            await _call(
                session,
                trace,
                "build_target_set",
                project=PROJECT,
                branch="main",
                name=target,
                document=DOCUMENT,
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

        ready = await _call(
            session,
            trace,
            "branch_merge_preflight",
            project=PROJECT,
            target_branch="target",
            source_branch="source",
        )
        assert ready["ready_for_publication"] is True
        assert ready["impact"]["total_affected_target_count"] == 2
        assert ready["validation_set"]["passed_targets"] == [
            "application",
            "mirror",
        ]
        assert ready["publication_tool"] == "branch_merge"
        assert ready["publication_arguments"]["validate_affected_targets"] is True

        branches = await _call(session, trace, "branch_list", project=PROJECT)
        heads = {item["name"]: item["head_revision_id"] for item in branches}
        assert heads["target"] == target_edit["revision_id"]
        assert heads["source"] == source_edit["revision_id"]

        merged = await _call(
            session,
            trace,
            ready["publication_tool"],
            **ready["publication_arguments"],
        )
        assert merged["affected_validation_enforced"] is True
        assert (
            merged["merge_validation_set"]["validation_set_id"]
            == ready["validation_set"]["validation_set_id"]
        )

        built = await _call(
            session,
            trace,
            "build_target_build",
            project=PROJECT,
            branch="target",
            name="application",
        )
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
        qgate = await _call(
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
            parent_id=qgate["node_id"],
            kind="symbol",
            value="H",
        )
        broken = await _call(
            session,
            trace,
            "branch_merge_preflight",
            project=PROJECT,
            target_branch="target",
            source_branch="broken",
        )
        assert broken["ready_for_publication"] is False
        assert broken["validation_set"]["failed_targets"] == [
            "application",
            "mirror",
        ]
        broken_error = await _call_error(
            session,
            trace,
            broken["publication_tool"],
            **broken["publication_arguments"],
        )
        assert broken_error["code"] == "MERGE_VALIDATION_FAILED"

        await _call(
            session,
            trace,
            "branch_create",
            project=PROJECT,
            branch="uncovered",
            from_branch="target",
        )
        await _call(
            session,
            trace,
            "node_set_atom",
            project=PROJECT,
            branch="uncovered",
            document=ORPHAN,
            node_id=orphan_atom["node_id"],
            value="changed but uncovered",
        )
        uncovered = await _call(
            session,
            trace,
            "branch_merge_preflight",
            project=PROJECT,
            target_branch="target",
            source_branch="uncovered",
        )
        assert uncovered["ready_for_publication"] is False
        assert uncovered["validation_set"]["coverage_passed"] is False
        assert uncovered["validation_set"]["validated_target_count"] == 0
        assert uncovered["impact"]["uncovered_changed_documents"] == [ORPHAN]

        allowed = await _call(
            session,
            trace,
            "branch_merge_preflight",
            project=PROJECT,
            target_branch="target",
            source_branch="uncovered",
            preview_id=uncovered["preview_id"],
            allow_uncovered_documents=True,
        )
        assert allowed["ready_for_publication"] is True
        assert allowed["publication_arguments"]["allow_uncovered_documents"] is True
        allowed_merge = await _call(
            session,
            trace,
            allowed["publication_tool"],
            **allowed["publication_arguments"],
        )
        assert allowed_merge["allow_uncovered_documents"] is True
        assert (
            allowed_merge["merge_validation_set"]["validation_set_id"]
            == allowed["validation_set"]["validation_set_id"]
        )

    (tmp_path / "merge-preflight-trace.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return trace


@pytest.mark.real_mcp
@pytest.mark.real_e2e
def test_real_mcp_composes_and_repeats_merge_preflight(tmp_path: Path) -> None:
    configured = os.environ.get("WEAVEC_BIN")
    if not configured:
        pytest.skip("WEAVEC_BIN is required for merge preflight qualification")
    compiler = Path(configured).resolve()
    assert compiler.is_file()
    trace = asyncio.run(_run(tmp_path, compiler))
    preflights = [entry for entry in trace if entry["tool"] == "branch_merge_preflight"]
    assert len(preflights) == 4
    assert preflights[0]["payload"]["result"]["ready_for_publication"] is True
    assert preflights[1]["payload"]["result"]["ready_for_publication"] is False
    assert preflights[2]["payload"]["result"]["validation_set"]["coverage_passed"] is False
    assert preflights[3]["payload"]["result"]["allow_uncovered_documents"] is True
