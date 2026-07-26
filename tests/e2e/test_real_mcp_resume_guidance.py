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


async def _run(tmp_path: Path) -> None:
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
        initialized = await session.initialize()
        instructions = getattr(initialized, "instructions", None)
        assert isinstance(instructions, str)
        normalized = " ".join(instructions.split())
        assert "branch_resume_snapshot" in instructions
        assert "before assembling state through separate reads" in normalized
        assert "branch_checkpoint_create" in normalized
        assert "Before transferring work" in normalized
        assert "branch_checkpoint_get" in normalized

        tools = await session.list_tools()
        names = {tool.name for tool in tools.tools}
        assert {
            "branch_resume_snapshot",
            "branch_checkpoint_create",
            "branch_checkpoint_get",
            "weave_help",
        } <= names

        resume = _payload(
            await session.call_tool("weave_help", arguments={"topic": "resume"})
        )
        assert resume["ok"] is True
        assert resume["help"]["revision"].startswith("Omit revision_id")
        assert "checkpoint_revision_id" in resume["help"]["checkpoint"]
        assert "branch_create_at_revision" in resume["help"]["continue"]

        checkpoint = _payload(
            await session.call_tool("weave_help", arguments={"topic": "checkpoint"})
        )
        assert checkpoint["ok"] is True
        assert "branch_checkpoint_create" in checkpoint["help"]["publish"]
        assert checkpoint["help"]["statuses"] == [
            "in_progress",
            "blocked",
            "ready_for_review",
            "complete",
        ]
        assert "branch_resume_snapshot" in checkpoint["help"]["resume"]

        workflow = _payload(
            await session.call_tool("weave_help", arguments={"topic": "workflow"})
        )
        assert workflow["ok"] is True
        assert workflow["help"]["steps"][0] == (
            "branch_resume_snapshot first when resuming existing work"
        )
        assert workflow["help"]["steps"][-1] == (
            "branch_checkpoint_create before handoff or stopping"
        )


@pytest.mark.real_mcp
def test_real_mcp_installs_resume_snapshot_guidance(tmp_path: Path) -> None:
    asyncio.run(_run(tmp_path))
