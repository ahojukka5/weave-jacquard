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
PROJECT = "merge-policy"
DOCUMENT = "main.weave"

SOURCE = """(program
  (name \"merge-policy\")
  (version \"0.1\")
  (entry main)
  (fn target_value
    (params)
    (returns i32)
    (do (return (const_i32 1))))
  (fn source_value
    (params)
    (returns i32)
    (do (return (const_i32 2))))
  (fn main
    (params)
    (returns i32)
    (do
      (return
        (add_i32
          (call_i32 target_value)
          (call_i32 source_value)))))
)
"""


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


async def _run_executable(
    session: ClientSession,
    trace: list[dict[str, Any]],
    *,
    branch: str,
    expected: int,
) -> None:
    built = await _call(
        session,
        trace,
        "build_target_build",
        project=PROJECT,
        branch=branch,
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
    assert completed.returncode == expected


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
        assert {
            "merge_policy_get",
            "merge_policy_set",
            "branch_merge_preflight",
            "branch_merge",
        } <= names

        await _call(session, trace, "project_initialize", project=PROJECT)
        imported = await _call(
            session,
            trace,
            "program_import",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            source=SOURCE,
        )
        one = await _call(
            session,
            trace,
            "node_find",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            kind="integer",
            value=1,
        )
        two = await _call(
            session,
            trace,
            "node_find",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            kind="integer",
            value=2,
        )
        assert len(one) == 1
        assert len(two) == 1
        target_constant = one[0]["node_id"]
        source_constant = two[0]["node_id"]

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

        strict = await _call(
            session,
            trace,
            "merge_policy_set",
            project=PROJECT,
            branch="main",
            require_preflight=True,
            require_affected_validation=True,
            allow_uncovered_documents=False,
            max_affected_targets=2,
        )
        assert strict["configured"] is True
        assert strict["revision_id"] != imported["revision_id"]

        for branch in ("target", "source"):
            await _call(
                session,
                trace,
                "branch_create",
                project=PROJECT,
                branch=branch,
                from_branch="main",
            )
        await _call(
            session,
            trace,
            "node_set_atom",
            project=PROJECT,
            branch="target",
            document=DOCUMENT,
            node_id=target_constant,
            value=10,
        )
        await _call(
            session,
            trace,
            "node_set_atom",
            project=PROJECT,
            branch="source",
            document=DOCUMENT,
            node_id=source_constant,
            value=20,
        )

        missing_preflight = await _call_error(
            session,
            trace,
            "branch_merge",
            project=PROJECT,
            target_branch="target",
            source_branch="source",
            validate_affected_targets=True,
        )
        assert missing_preflight["code"] == "MERGE_POLICY_PREFLIGHT_REQUIRED"

        ready = await _call(
            session,
            trace,
            "branch_merge_preflight",
            project=PROJECT,
            target_branch="target",
            source_branch="source",
        )
        assert ready["ready_for_publication"] is True
        assert ready["target_merge_policy"]["policy_hash"] == strict["policy_hash"]
        assert ready["source_merge_policy"]["policy_hash"] == strict["policy_hash"]
        assert ready["source_policy_ignored"] is False
        assert ready["validation_set"]["max_target_validations"] == 2
        assert ready["publication_arguments"]["preflight_id"] == ready["preflight_id"]

        merged = await _call(
            session,
            trace,
            ready["publication_tool"],
            **ready["publication_arguments"],
        )
        assert merged["preflight_enforced"] is True
        assert merged["preflight_id"] == ready["preflight_id"]
        assert merged["merge_policy_enforced"] is True
        assert merged["target_merge_policy"]["policy_hash"] == strict["policy_hash"]
        assert merged["merge_validation_set"]["validation_set_id"] == ready[
            "validation_set"
        ]["validation_set_id"]
        await _run_executable(session, trace, branch="target", expected=30)

        await _call(
            session,
            trace,
            "branch_create",
            project=PROJECT,
            branch="weak-source",
            from_branch="target",
        )
        weak = await _call(
            session,
            trace,
            "merge_policy_set",
            project=PROJECT,
            branch="weak-source",
            require_preflight=False,
            require_affected_validation=False,
            allow_uncovered_documents=True,
            max_affected_targets=64,
        )
        await _call(
            session,
            trace,
            "node_set_atom",
            project=PROJECT,
            branch="weak-source",
            document=DOCUMENT,
            node_id=source_constant,
            value=21,
        )

        forbidden = await _call_error(
            session,
            trace,
            "branch_merge_preflight",
            project=PROJECT,
            target_branch="target",
            source_branch="weak-source",
            allow_uncovered_documents=True,
        )
        assert forbidden["code"] == "MERGE_POLICY_VIOLATION"

        protected = await _call(
            session,
            trace,
            "branch_merge_preflight",
            project=PROJECT,
            target_branch="target",
            source_branch="weak-source",
        )
        assert protected["ready_for_publication"] is True
        assert protected["source_policy_ignored"] is True
        assert protected["target_merge_policy"]["policy_hash"] == strict["policy_hash"]
        assert protected["source_merge_policy"]["policy_hash"] == weak["policy_hash"]
        protected_merge = await _call(
            session,
            trace,
            protected["publication_tool"],
            **protected["publication_arguments"],
        )
        assert protected_merge["source_policy_ignored"] is True
        assert protected_merge["target_merge_policy"]["policy_hash"] == strict[
            "policy_hash"
        ]
        await _run_executable(session, trace, branch="target", expected=31)

        branches = await _call(session, trace, "branch_list", project=PROJECT)
        target_before_limit = {
            item["name"]: item["head_revision_id"] for item in branches
        }["target"]
        limited = await _call(
            session,
            trace,
            "merge_policy_set",
            project=PROJECT,
            branch="target",
            require_preflight=True,
            require_affected_validation=True,
            allow_uncovered_documents=False,
            max_affected_targets=1,
        )
        historical = await _call(
            session,
            trace,
            "merge_policy_get",
            project=PROJECT,
            branch="target",
            revision_id=target_before_limit,
        )
        assert historical["max_affected_targets"] == 2
        assert limited["max_affected_targets"] == 1

        await _call(
            session,
            trace,
            "branch_create",
            project=PROJECT,
            branch="fanout",
            from_branch="target",
        )
        await _call(
            session,
            trace,
            "node_set_atom",
            project=PROJECT,
            branch="fanout",
            document=DOCUMENT,
            node_id=target_constant,
            value=11,
        )
        too_many = await _call_error(
            session,
            trace,
            "branch_merge_preflight",
            project=PROJECT,
            target_branch="target",
            source_branch="fanout",
        )
        assert too_many["code"] == "TOO_MANY_AFFECTED_TARGETS"

        relaxed = await _call(
            session,
            trace,
            "merge_policy_set",
            project=PROJECT,
            branch="target",
            require_preflight=True,
            require_affected_validation=True,
            allow_uncovered_documents=False,
            max_affected_targets=2,
        )
        allowed = await _call(
            session,
            trace,
            "branch_merge_preflight",
            project=PROJECT,
            target_branch="target",
            source_branch="fanout",
        )
        assert allowed["ready_for_publication"] is True
        assert allowed["source_policy_ignored"] is True
        assert allowed["target_merge_policy"]["policy_hash"] == relaxed["policy_hash"]
        assert allowed["source_merge_policy"]["policy_hash"] == limited["policy_hash"]
        await _call(
            session,
            trace,
            allowed["publication_tool"],
            **allowed["publication_arguments"],
        )
        await _run_executable(session, trace, branch="target", expected=32)

    (tmp_path / "merge-policy-trace.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return trace


@pytest.mark.real_mcp
@pytest.mark.real_e2e
def test_real_mcp_enforces_target_branch_merge_policy(tmp_path: Path) -> None:
    configured = os.environ.get("WEAVEC_BIN")
    if not configured:
        pytest.skip("WEAVEC_BIN is required for merge policy qualification")
    compiler = Path(configured).resolve()
    assert compiler.is_file()

    trace = asyncio.run(_run(tmp_path, compiler))

    policies = [entry for entry in trace if entry["tool"] == "merge_policy_set"]
    preflights = [
        entry for entry in trace if entry["tool"] == "branch_merge_preflight"
    ]
    assert len(policies) == 4
    assert len(preflights) == 5
    assert preflights[0]["payload"]["result"]["ready_for_publication"] is True
    assert preflights[1]["payload"]["error"]["code"] == "MERGE_POLICY_VIOLATION"
    assert preflights[2]["payload"]["result"]["source_policy_ignored"] is True
    assert preflights[3]["payload"]["error"]["code"] == "TOO_MANY_AFFECTED_TARGETS"
    assert preflights[4]["payload"]["result"]["ready_for_publication"] is True
