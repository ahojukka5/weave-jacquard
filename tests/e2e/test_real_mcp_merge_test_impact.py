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
PROJECT = "merge-candidate-test-impact"
PROGRAM_V2 = """(program
  (name \"merge-candidate-test-impact\")
  (version \"0.2\"))
"""
REQUIRED_TOOLS = {
    "branch_create_at_revision",
    "branch_list",
    "branch_merge_preview",
    "branch_merge_test_impact",
    "build_target_set",
    "program_create",
    "program_import",
    "project_initialize",
    "test_target_set",
}


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


def _branch_heads(branches: list[dict[str, Any]]) -> dict[str, str]:
    return {str(item["name"]): str(item["head_revision_id"]) for item in branches}


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
            "WEAVE_TEST_RUN_ROOT": str(tmp_path / "runs"),
        }
    )
    return environment


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
        by_name = {tool.name: tool for tool in tools.tools}
        assert set(by_name) >= REQUIRED_TOOLS

        help_payload = await _call_payload(
            session,
            trace,
            "weave_help",
            topic="merge_test_impact",
        )
        assert help_payload["ok"] is True
        help_result = help_payload["help"]
        assert "merged_root_hash" in help_result["preview"]
        assert "candidate_execution=null" in help_result["execution"]

        await _call(session, trace, "project_initialize", project=PROJECT)
        heads = _branch_heads(await _call(session, trace, "branch_list", project=PROJECT))
        initial = heads["main"]
        program = await _call(
            session,
            trace,
            "program_create",
            project=PROJECT,
            branch="main",
            document="main.weave",
            program_name=PROJECT,
            expected_revision_id=initial,
        )
        target = await _call(
            session,
            trace,
            "build_target_set",
            project=PROJECT,
            branch="main",
            name="application",
            document="main.weave",
            expected_revision_id=program["revision_id"],
        )
        definition = await _call(
            session,
            trace,
            "test_target_set",
            project=PROJECT,
            branch="main",
            name="smoke",
            build_target="application",
            expected_exit_code=0,
            expected_stdout="",
            expected_stderr="",
            expected_revision_id=target["revision_id"],
        )
        base_revision = definition["revision_id"]
        await _call(
            session,
            trace,
            "branch_create_at_revision",
            project=PROJECT,
            branch="feature",
            revision_id=base_revision,
        )
        feature = await _call(
            session,
            trace,
            "program_import",
            project=PROJECT,
            branch="feature",
            document="main.weave",
            source=PROGRAM_V2,
            replace=True,
            expected_revision_id=base_revision,
        )
        heads_before = _branch_heads(
            await _call(session, trace, "branch_list", project=PROJECT)
        )
        assert heads_before == {
            "feature": feature["revision_id"],
            "main": base_revision,
        }

        preview = await _call(
            session,
            trace,
            "branch_merge_preview",
            project=PROJECT,
            target_branch="main",
            source_branch="feature",
        )
        assert preview["mergeable"] is True
        assert preview["target_head_revision_id"] == base_revision
        assert preview["source_head_revision_id"] == feature["revision_id"]
        assert preview["base_revision_id"] == base_revision

        plan = await _call(
            session,
            trace,
            "branch_merge_test_impact",
            project=PROJECT,
            target_branch="main",
            source_branch="feature",
            preview_id=preview["preview_id"],
            limit=10,
            evidence_limit=10,
        )
        assert plan["preview_id"] == preview["preview_id"]
        assert plan["merged_root_hash"] == preview["merged_root_hash"]
        assert plan["target_head_revision_id"] == base_revision
        assert plan["source_head_revision_id"] == feature["revision_id"]
        assert plan["changed_program_documents"] == ["main.weave"]
        assert plan["changed_build_targets"] == []
        assert plan["changed_test_targets"] == []
        assert plan["uncovered_changed_program_documents"] == []
        assert [item["name"] for item in plan["impacted_tests"]] == ["smoke"]
        assert plan["impacted_tests"][0]["reasons"] == ["source_changed"]
        assert plan["impacted_tests"][0]["definition_subject"] == {
            "kind": "virtual_merge_candidate",
            "preview_id": preview["preview_id"],
            "committed_revision_id": None,
        }
        assert plan["complete_selection"] is True
        assert plan["candidate_execution"] is None
        assert plan["interpretation"]["executes_tests"] is False
        assert plan["interpretation"]["publishes_merge"] is False

        repeated = await _call(
            session,
            trace,
            "branch_merge_test_impact",
            project=PROJECT,
            target_branch="main",
            source_branch="feature",
            preview_id=preview["preview_id"],
            limit=10,
            evidence_limit=10,
        )
        assert repeated["plan_id"] == plan["plan_id"]
        assert repeated["impacted_tests"] == plan["impacted_tests"]
        heads_after = _branch_heads(
            await _call(session, trace, "branch_list", project=PROJECT)
        )
        assert heads_after == heads_before

    return trace


@pytest.mark.real_mcp
def test_real_mcp_plans_virtual_merge_candidate_tests(tmp_path: Path) -> None:
    trace = asyncio.run(_run(tmp_path))
    (tmp_path / "merge-test-impact-trace.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    impact_calls = [
        entry for entry in trace if entry["tool"] == "branch_merge_test_impact"
    ]
    assert len(impact_calls) == 2
    assert impact_calls[0]["payload"]["result"]["plan_id"] == impact_calls[1][
        "payload"
    ]["result"]["plan_id"]
