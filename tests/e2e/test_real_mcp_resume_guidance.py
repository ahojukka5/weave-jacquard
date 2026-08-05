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
        assert "branch_checkpoint_history_page" in normalized
        assert "revision_scan_limit" in normalized
        assert "branch_checkpoint_compare" in normalized
        assert "does not itself prove completion" in normalized
        assert "project_agent_status_page" in normalized
        assert "catalog_id" in normalized
        assert "next_after_branch" in normalized
        assert "checkpoint_scan_limit" in normalized
        assert "do not prove inactivity" in normalized
        assert "review readiness" in normalized
        assert "project_merge_queue_page" in normalized
        assert "next_after_source" in normalized
        assert "conflict_limit" in normalized
        assert "changed_document_limit" in normalized
        assert "structural preview success only" in normalized
        assert "branch_merge_preflight" in normalized
        assert "does not represent priority" in normalized
        assert "project_merge_impact_queue_page" in normalized
        assert "affected_target_limit" in normalized
        assert "coverage_document_limit" in normalized
        assert "Conflicted sources stop before impact analysis" in normalized
        assert "target revision policy as authoritative" in normalized
        assert "source policy is visible but cannot weaken" in normalized
        assert "No compiler or build validation runs" in normalized
        assert "branch_merge_impact" in normalized
        assert "selected_merge_preflight_batch" in normalized
        assert "1–5 unique source names" in normalized
        assert "does not select, rank, or expand" in normalized
        assert "allow_uncovered_sources" in normalized
        assert "independently for every selected source" in normalized
        assert "selected or unselected branch-head change" in normalized
        assert "never publishes a merge" in normalized
        assert "ready_for_publication" in normalized
        assert "publication_arguments" in normalized
        assert "selected_merge_train_preview" in normalized
        assert "1–10 unique source branches" in normalized
        assert "in-memory virtual target" in normalized
        assert "order_introduced_conflict" in normalized
        assert "order_removed_conflict" in normalized
        assert "later no-change redundancy" in normalized
        assert "stops at the first unresolved train conflict" in normalized
        assert "No compiler, preflight, build, or merge publication runs" in normalized
        assert "Only the first clean step" in normalized
        assert "fresh catalog and preflight" in normalized
        assert "does not itself express priority" in normalized

        tools = await session.list_tools()
        names = {tool.name for tool in tools.tools}
        assert {
            "branch_resume_snapshot",
            "branch_checkpoint_create",
            "branch_checkpoint_get",
            "branch_checkpoint_history_page",
            "branch_checkpoint_compare",
            "project_agent_status_page",
            "project_merge_queue_page",
            "project_merge_impact_queue_page",
            "selected_merge_preflight_batch",
            "selected_merge_train_preview",
            "weave_help",
        } <= names

        resume = _payload(await session.call_tool("weave_help", arguments={"topic": "resume"}))
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
        assert "branch_checkpoint_history_page" in checkpoint["help"]["history"]
        assert "branch_checkpoint_compare" in checkpoint["help"]["compare"]
        assert "branch_resume_snapshot" in checkpoint["help"]["resume"]

        timeline = _payload(
            await session.call_tool(
                "weave_help",
                arguments={"topic": "checkpoint_timeline"},
            )
        )
        assert timeline["ok"] is True
        assert "revision_scan_limit" in timeline["help"]["page"]
        assert "next_revision_id" in timeline["help"]["continuation"]
        assert "branch_checkpoint_compare" in timeline["help"]["compare"]
        assert "does not prove completion" in timeline["help"]["interpretation"]

        status = _payload(
            await session.call_tool(
                "weave_help",
                arguments={"topic": "agent_status"},
            )
        )
        assert status["ok"] is True
        assert "project_agent_status_page" in status["help"]["page"]
        assert "catalog_id" in status["help"]["catalog"]
        assert "checkpoint_scan_limit" in status["help"]["bounds"]
        assert status["help"]["states"] == [
            "head",
            "behind_head",
            "not_found_within_scan",
            "none_in_first_parent_history",
        ]
        assert "do not prove inactivity" in status["help"]["interpretation"]

        queue = _payload(
            await session.call_tool(
                "weave_help",
                arguments={"topic": "merge_queue"},
            )
        )
        assert queue["ok"] is True
        assert "project_merge_queue_page" in queue["help"]["page"]
        assert "next_after_source" in queue["help"]["catalog"]
        assert "checkpoint_scan_limit" in queue["help"]["bounds"]
        assert queue["help"]["classifications"] == [
            "clean_changes",
            "clean_no_changes",
            "conflicted",
        ]
        assert "structural preview succeeded only" in queue["help"]["readiness"]
        assert "preflight" in queue["help"]["follow_up"]
        assert "does not express priority" in queue["help"]["ordering"]

        impact = _payload(
            await session.call_tool(
                "weave_help",
                arguments={"topic": "merge_impact_queue"},
            )
        )
        assert impact["ok"] is True
        assert "project_merge_impact_queue_page" in impact["help"]["page"]
        assert "affected_target_limit" in impact["help"]["bounds"]
        assert "coverage_document_limit" in impact["help"]["bounds"]
        assert impact["help"]["classifications"] == [
            "conflicted",
            "covered_program_changes",
            "uncovered_program_changes",
            "target_definition_changes_only",
            "no_changes",
        ]
        assert "cannot weaken" in impact["help"]["policy"]
        assert "not compiler validation" in impact["help"]["coverage"]
        assert "No compiler" in impact["help"]["compiler"]
        assert "do not prove compiler correctness" in impact["help"]["readiness"]

        selected = _payload(
            await session.call_tool(
                "weave_help",
                arguments={"topic": "selected_preflight_batch"},
            )
        )
        assert selected["ok"] is True
        assert "selected_merge_preflight_batch" in selected["help"]["selection"]
        assert "unselected branches" in selected["help"]["catalog"]
        assert "allow_uncovered_sources" in selected["help"]["overrides"]
        assert "branch_merge_preflight" in selected["help"]["execution"]
        assert "At most five sources" in selected["help"]["bounds"]
        assert selected["help"]["outcomes"] == [
            "ready",
            "not_ready",
            "conflict",
            "policy_error",
            "other_error",
        ]
        assert "publishes no merge" in selected["help"]["publication"]
        assert "publication_arguments" in selected["help"]["publication"]

        train = _payload(
            await session.call_tool(
                "weave_help",
                arguments={"topic": "merge_train"},
            )
        )
        assert train["ok"] is True
        assert "selected_merge_train_preview" in train["help"]["selection"]
        assert "unselected branches" in train["help"]["catalog"]
        assert train["help"]["relations"] == [
            "consistent_clean",
            "consistent_conflict",
            "order_introduced_conflict",
            "order_removed_conflict",
        ]
        assert "no_changes" in train["help"]["redundancy"]
        assert "first unresolved train conflict" in train["help"]["stopping"]
        assert "no compiler" in train["help"]["execution"]
        assert "refresh the complete catalog" in train["help"]["publication"]
        assert "can change conflicts and redundancy" in train["help"]["ordering"]

        read = _payload(await session.call_tool("weave_help", arguments={"topic": "read"}))
        assert read["ok"] is True
        assert "project_agent_status_page" in read["help"]["tools"]
        assert "project_merge_queue_page" in read["help"]["tools"]
        assert "project_merge_impact_queue_page" in read["help"]["tools"]
        assert "selected_merge_preflight_batch" in read["help"]["tools"]
        assert "selected_merge_train_preview" in read["help"]["tools"]

        workflow = _payload(await session.call_tool("weave_help", arguments={"topic": "workflow"}))
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
