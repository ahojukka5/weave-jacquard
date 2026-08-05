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
PROJECT = "agent-resume-snapshot"
DOCUMENT = "main.weave"
LIBRARY = """(program
  (name \"resume-library\")
  (version \"0.1\"))
"""
SUPPORT = LIBRARY.replace('name "resume-library"', 'name "resume-support"')


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
    return environment


def _schema(tool: Any) -> dict[str, Any]:
    value = _attribute(tool, "input_schema", "inputSchema")
    assert isinstance(value, dict), tool
    return value


def _document(snapshot: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [item for item in snapshot["program_documents"] if item["document"] == name]
    assert len(matches) == 1, snapshot["program_documents"]
    return matches[0]


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
        assert "branch_resume_snapshot" in by_name
        properties = _schema(by_name["branch_resume_snapshot"]).get("properties")
        assert isinstance(properties, dict)
        assert {
            "revision_id",
            "document_limit",
            "target_limit",
            "target_source_limit",
            "context_limit",
            "branch_limit",
            "history_limit",
            "operation_limit",
        } <= set(properties)

        await _call(session, trace, "project_initialize", project=PROJECT)
        program = await _call(
            session,
            trace,
            "program_create",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            program_name=PROJECT,
        )
        library = await _call(
            session,
            trace,
            "program_import",
            project=PROJECT,
            branch="main",
            document="library.weave",
            source=LIBRARY,
            expected_revision_id=program["revision_id"],
        )
        support = await _call(
            session,
            trace,
            "program_import",
            project=PROJECT,
            branch="main",
            document="support.weave",
            source=SUPPORT,
            expected_revision_id=library["revision_id"],
        )
        target = await _call(
            session,
            trace,
            "build_target_set",
            project=PROJECT,
            branch="main",
            name="application",
            document=DOCUMENT,
            additional_documents=["library.weave", "support.weave"],
            expected_revision_id=support["revision_id"],
        )
        context = await _call(
            session,
            trace,
            "context_add",
            project=PROJECT,
            branch="main",
            scope_kind="document",
            scope_name=DOCUMENT,
            title="Resume invariant",
            body="Every summary comes from one immutable revision.",
            expected_revision_id=target["revision_id"],
        )
        reviewed_policy = await _call(
            session,
            trace,
            "merge_policy_set",
            project=PROJECT,
            branch="main",
            require_preflight=True,
            require_affected_validation=True,
            allow_uncovered_documents=False,
            max_affected_targets=5,
            expected_revision_id=context["revision_id"],
        )
        reviewed_revision = str(reviewed_policy["revision_id"])
        await _call(
            session,
            trace,
            "branch_create_at_revision",
            project=PROJECT,
            branch="reviewed",
            revision_id=reviewed_revision,
        )

        reviewed = await _call(
            session,
            trace,
            "branch_resume_snapshot",
            project=PROJECT,
            branch="main",
        )
        assert reviewed["revision_id"] == reviewed_revision
        assert reviewed["revision_is_branch_head"] is True
        assert reviewed["program_document_count"] == 3
        assert reviewed["build_target_count"] == 1
        assert reviewed["build_targets"][0]["additional_document_count"] == 2
        assert reviewed["build_targets"][0]["additional_documents_truncated"] is False
        assert reviewed["merge_policy"]["max_affected_targets"] == 5
        assert reviewed["context_count"] == 2
        assert reviewed["branch_count"] == 2
        assert reviewed["operation_count"] == 1
        assert reviewed["reproducible_fork"]["arguments"]["revision_id"] == (reviewed_revision)
        assert reviewed["build_recovery"]["arguments"]["revision_id"] == (reviewed_revision)

        advanced = await _call(
            session,
            trace,
            "node_create_form",
            project=PROJECT,
            branch="main",
            document=DOCUMENT,
            parent_id=program["node_id"],
            head="advanced",
            expected_revision_id=reviewed_revision,
        )
        latest_policy = await _call(
            session,
            trace,
            "merge_policy_set",
            project=PROJECT,
            branch="main",
            require_preflight=True,
            require_affected_validation=True,
            allow_uncovered_documents=False,
            max_affected_targets=3,
            expected_revision_id=advanced["revision_id"],
        )

        historical = await _call(
            session,
            trace,
            "branch_resume_snapshot",
            project=PROJECT,
            branch="main",
            revision_id=reviewed_revision,
        )
        current = await _call(
            session,
            trace,
            "branch_resume_snapshot",
            project=PROJECT,
            branch="main",
        )
        assert historical["branch_head_revision_id"] == latest_policy["revision_id"]
        assert historical["revision_is_branch_head"] is False
        assert historical["merge_policy"]["max_affected_targets"] == 5
        assert current["merge_policy"]["max_affected_targets"] == 3
        assert historical["context_count"] == 2
        assert current["context_count"] == 3
        assert (
            _document(historical, DOCUMENT)["source_sha256"]
            != _document(
                current,
                DOCUMENT,
            )["source_sha256"]
        )
        assert historical["snapshot_id"] != current["snapshot_id"]

        bounded = await _call(
            session,
            trace,
            "branch_resume_snapshot",
            project=PROJECT,
            branch="main",
            revision_id=reviewed_revision,
            document_limit=1,
            target_limit=1,
            target_source_limit=1,
            context_limit=1,
            branch_limit=1,
            history_limit=1,
            operation_limit=1,
        )
        assert bounded["program_documents_truncated"] is True
        assert bounded["build_targets"][0]["additional_documents_truncated"] is True
        assert bounded["contexts_truncated"] is True
        assert bounded["branches_truncated"] is True
        assert bounded["history"]["has_more"] is True

    (tmp_path / "resume-snapshot-trace.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return trace


@pytest.mark.real_mcp
def test_real_mcp_returns_revision_consistent_resume_snapshots(tmp_path: Path) -> None:
    trace = asyncio.run(_run(tmp_path))
    snapshots = [entry for entry in trace if entry["tool"] == "branch_resume_snapshot"]
    assert len(snapshots) == 4
    assert all(entry["payload"]["ok"] is True for entry in snapshots)
    assert all(len(entry["payload"]["result"]["snapshot_id"]) == 64 for entry in snapshots)
