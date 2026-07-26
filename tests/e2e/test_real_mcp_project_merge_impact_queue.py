from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "project-merge-impact-queue"
TOOL = "project_merge_impact_queue_page"


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


async def _call_error(
    session: ClientSession,
    trace: list[dict[str, Any]],
    tool_name: str,
    **arguments: Any,
) -> dict[str, Any]:
    payload = await _call_payload(session, trace, tool_name, **arguments)
    assert payload.get("ok") is False, payload
    return payload["error"]


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
    environment.pop("WEAVEC_BIN", None)
    environment.pop("WEAVEC_SOURCE_ROOT", None)
    return environment


def _schema(tool: Any) -> dict[str, Any]:
    value = _attribute(tool, "input_schema", "inputSchema")
    assert isinstance(value, dict), tool
    return value


async def _program_with_atoms(
    session: ClientSession,
    trace: list[dict[str, Any]],
    *,
    document: str,
    values: list[str],
) -> dict[str, Any]:
    created = await _call(
        session,
        trace,
        "program_create",
        project=PROJECT,
        branch="main",
        document=document,
        program_name=document,
    )
    revision_id = str(created["revision_id"])
    atoms: list[str] = []
    for value in values:
        added = await _call(
            session,
            trace,
            "node_add_atom",
            project=PROJECT,
            branch="main",
            document=document,
            parent_id=created["node_id"],
            kind="string",
            value=value,
            expected_revision_id=revision_id,
        )
        revision_id = str(added["revision_id"])
        atoms.append(str(added["node_id"]))
    return {
        "root_id": str(created["node_id"]),
        "atom_ids": atoms,
        "revision_id": revision_id,
    }


async def _checkpoint(
    session: ClientSession,
    trace: list[dict[str, Any]],
    *,
    branch: str,
    revision_id: str,
    objective: str,
) -> Any:
    return await _call(
        session,
        trace,
        "branch_checkpoint_create",
        project=PROJECT,
        branch=branch,
        objective=objective,
        summary=f"Checkpoint for {branch}",
        completed=["prepared impact candidate"],
        next_steps=["review target coverage"],
        validation=["syntax"],
        expected_revision_id=revision_id,
    )


async def _run(tmp_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
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
        assert {
            TOOL,
            "project_merge_queue_page",
            "branch_merge_impact",
            "merge_policy_set",
            "build_target_set",
        } <= set(by_name)
        properties = _schema(by_name[TOOL]).get("properties")
        assert isinstance(properties, dict)
        assert {
            "target_branch",
            "start_after_source",
            "catalog_id",
            "limit",
            "checkpoint_scan_limit",
            "conflict_limit",
            "changed_document_limit",
            "affected_target_limit",
            "coverage_document_limit",
        } <= set(properties)

        await _call(session, trace, "project_initialize", project=PROJECT)
        main = await _program_with_atoms(
            session,
            trace,
            document="main.weave",
            values=["conflict", "covered"],
        )
        lib = await _program_with_atoms(
            session,
            trace,
            document="lib.weave",
            values=["lib"],
        )
        orphan = await _program_with_atoms(
            session,
            trace,
            document="orphan.weave",
            values=["orphan"],
        )
        await _program_with_atoms(
            session,
            trace,
            document="spare.weave",
            values=["spare"],
        )

        for name, document, additional in (
            ("application", "main.weave", ["lib.weave"]),
            ("main-only", "main.weave", []),
            ("spare", "spare.weave", []),
        ):
            await _call(
                session,
                trace,
                "build_target_set",
                project=PROJECT,
                branch="main",
                name=name,
                document=document,
                additional_documents=additional,
            )
        target_policy = await _call(
            session,
            trace,
            "merge_policy_set",
            project=PROJECT,
            branch="main",
            require_preflight=True,
            require_affected_validation=True,
            allow_uncovered_documents=False,
            max_affected_targets=3,
        )
        base_revision = str(target_policy["revision_id"])
        for branch in ("conflict", "covered", "target-only", "uncovered"):
            await _call(
                session,
                trace,
                "branch_create_at_revision",
                project=PROJECT,
                branch=branch,
                revision_id=base_revision,
            )

        covered_policy = await _call(
            session,
            trace,
            "merge_policy_set",
            project=PROJECT,
            branch="covered",
            require_preflight=False,
            require_affected_validation=False,
            allow_uncovered_documents=True,
            max_affected_targets=10,
        )
        covered_main = await _call(
            session,
            trace,
            "node_set_atom",
            project=PROJECT,
            branch="covered",
            document="main.weave",
            node_id=main["atom_ids"][1],
            value="covered-main",
            expected_revision_id=covered_policy["revision_id"],
        )
        covered_lib = await _call(
            session,
            trace,
            "node_set_atom",
            project=PROJECT,
            branch="covered",
            document="lib.weave",
            node_id=lib["atom_ids"][0],
            value="covered-lib",
            expected_revision_id=covered_main["revision_id"],
        )
        covered_checkpoint = await _checkpoint(
            session,
            trace,
            branch="covered",
            revision_id=str(covered_lib["revision_id"]),
            objective="Review covered program changes",
        )
        conflict_checkpoint = await _checkpoint(
            session,
            trace,
            branch="conflict",
            revision_id=base_revision,
            objective="Resolve stable atom conflict",
        )
        conflict_head = await _call(
            session,
            trace,
            "node_set_atom",
            project=PROJECT,
            branch="conflict",
            document="main.weave",
            node_id=main["atom_ids"][0],
            value="source-conflict",
            expected_revision_id=conflict_checkpoint["revision_id"],
        )
        uncovered_head = await _call(
            session,
            trace,
            "node_set_atom",
            project=PROJECT,
            branch="uncovered",
            document="orphan.weave",
            node_id=orphan["atom_ids"][0],
            value="source-orphan",
            expected_revision_id=base_revision,
        )
        target_only = await _call(
            session,
            trace,
            "build_target_set",
            project=PROJECT,
            branch="target-only",
            name="application",
            document="main.weave",
            additional_documents=["lib.weave", "orphan.weave"],
            expected_revision_id=base_revision,
        )
        target_head = await _call(
            session,
            trace,
            "node_set_atom",
            project=PROJECT,
            branch="main",
            document="main.weave",
            node_id=main["atom_ids"][0],
            value="target-conflict",
            expected_revision_id=base_revision,
        )
        await _call(
            session,
            trace,
            "branch_create_at_revision",
            project=PROJECT,
            branch="noop",
            revision_id=target_head["revision_id"],
        )

        heads_before = {
            item["name"]: item["head_revision_id"]
            for item in await _call(
                session,
                trace,
                "branch_list",
                project=PROJECT,
            )
        }
        first = await _call(
            session,
            trace,
            TOOL,
            project=PROJECT,
            target_branch="main",
            limit=3,
            checkpoint_scan_limit=20,
            conflict_limit=1,
            changed_document_limit=1,
            affected_target_limit=1,
            coverage_document_limit=1,
        )
        assert first["source_catalog_count"] == 5
        assert first["next_after_source"] == "noop"
        assert [item["source_branch"] for item in first["sources"]] == [
            "conflict",
            "covered",
            "noop",
        ]
        assert first["target_merge_policy"]["policy_hash"] == target_policy[
            "policy_hash"
        ]
        assert "no compiler or build validation was run" in first["compiler_note"]

        conflict = first["sources"][0]
        assert conflict["impact_classification"] == "conflicted"
        assert conflict["impact"] is None
        assert conflict["impact_call"] is None
        assert conflict["source_head_revision_id"] == conflict_head["revision_id"]

        covered = first["sources"][1]
        assert covered["impact_classification"] == "covered_program_changes"
        assert covered["impact"]["changed_program_document_count"] == 2
        assert covered["impact"]["changed_program_documents_truncated"] is True
        assert covered["impact"]["total_affected_target_count"] == 2
        assert covered["impact"]["affected_targets_truncated"] is True
        assert covered["merge_policy"]["source_policy_ignored"] is True
        assert covered["merge_policy"]["source"]["policy_hash"] == covered_policy[
            "policy_hash"
        ]
        assert covered["source_checkpoint"]["checkpoint_state"] == "head"
        assert covered["source_head_revision_id"] == covered_checkpoint["revision_id"]

        replayed_impact = await _call(
            session,
            trace,
            covered["impact_call"]["tool"],
            **covered["impact_call"]["arguments"],
        )
        assert replayed_impact["preview_id"] == covered["preview_id"]
        assert replayed_impact["target_head_revision_id"] == target_head["revision_id"]
        assert replayed_impact["source_head_revision_id"] == covered_checkpoint[
            "revision_id"
        ]
        assert replayed_impact["uncovered_changed_documents"] == []

        noop = first["sources"][2]
        assert noop["impact_classification"] == "no_changes"
        assert noop["impact"]["total_affected_target_count"] == 0

        second = await _call(
            session,
            trace,
            TOOL,
            project=PROJECT,
            target_branch="main",
            start_after_source=first["next_after_source"],
            catalog_id=first["catalog_id"],
            limit=3,
            checkpoint_scan_limit=20,
            conflict_limit=1,
            changed_document_limit=1,
            affected_target_limit=1,
            coverage_document_limit=1,
        )
        assert [item["source_branch"] for item in second["sources"]] == [
            "target-only",
            "uncovered",
        ]
        target_only_entry = second["sources"][0]
        assert target_only_entry["source_head_revision_id"] == target_only[
            "revision_id"
        ]
        assert target_only_entry["impact_classification"] == (
            "target_definition_changes_only"
        )
        assert target_only_entry["impact"]["changed_target_document_count"] == 1

        uncovered = second["sources"][1]
        assert uncovered["source_head_revision_id"] == uncovered_head["revision_id"]
        assert uncovered["impact_classification"] == "uncovered_program_changes"
        assert uncovered["impact"]["uncovered_changed_documents"] == [
            "orphan.weave"
        ]
        assert uncovered["coverage_gate"] == {
            "uncovered_documents_present": True,
            "target_allows_uncovered_documents": False,
            "override_possible": False,
        }

        heads_after_reads = {
            item["name"]: item["head_revision_id"]
            for item in await _call(
                session,
                trace,
                "branch_list",
                project=PROJECT,
            )
        }
        assert heads_after_reads == heads_before

        later_covered = await _call(
            session,
            trace,
            "program_create",
            project=PROJECT,
            branch="covered",
            document="later.weave",
            program_name="later",
            expected_revision_id=covered_checkpoint["revision_id"],
        )
        stale = await _call_error(
            session,
            trace,
            TOOL,
            project=PROJECT,
            target_branch="main",
            start_after_source=first["next_after_source"],
            catalog_id=first["catalog_id"],
            limit=3,
        )
        assert stale["code"] == "STALE_PROJECT_MERGE_QUEUE_CATALOG"
        refreshed = await _call(
            session,
            trace,
            TOOL,
            project=PROJECT,
            target_branch="main",
            limit=5,
            checkpoint_scan_limit=20,
        )
        assert refreshed["catalog_id"] != first["catalog_id"]
        refreshed_covered = [
            item for item in refreshed["sources"] if item["source_branch"] == "covered"
        ][0]
        assert refreshed_covered["source_head_revision_id"] == later_covered[
            "revision_id"
        ]
        assert refreshed_covered["source_checkpoint"]["checkpoint_state"] == (
            "behind_head"
        )
        assert refreshed_covered["source_checkpoint"]["revisions_since_checkpoint"] == 1

    return trace, {
        "target_policy": target_policy,
        "covered_policy": covered_policy,
        "covered_checkpoint": covered_checkpoint,
        "conflict_head": conflict_head,
        "uncovered_head": uncovered_head,
        "target_only": target_only,
        "target_head": target_head,
        "later_covered": later_covered,
    }


def _verify_read_only_database(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "jacquard.db")
    connection.row_factory = sqlite3.Row
    try:
        queue_operations = connection.execute(
            """SELECT COUNT(*) AS count FROM operations
               WHERE operation_kind LIKE '%merge_impact_queue%'"""
        ).fetchone()["count"]
        assert queue_operations == 0
        merge_revisions = connection.execute(
            "SELECT COUNT(*) AS count FROM revisions WHERE parent2_id IS NOT NULL"
        ).fetchone()["count"]
        assert merge_revisions == 0
        branch_count = connection.execute(
            "SELECT COUNT(*) AS count FROM branches"
        ).fetchone()["count"]
        assert branch_count == 6
    finally:
        connection.close()


@pytest.mark.real_mcp
def test_real_mcp_pages_project_merge_impact_queue(tmp_path: Path) -> None:
    trace, state = asyncio.run(_run(tmp_path))
    _verify_read_only_database(tmp_path)
    (tmp_path / "project-merge-impact-queue-trace.json").write_text(
        json.dumps({"trace": trace, "state": state}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    reads = [entry for entry in trace if entry["tool"] == TOOL]
    assert len(reads) == 4
    assert sum(entry["payload"]["ok"] is True for entry in reads) == 3
    assert [
        entry["payload"]["error"]["code"]
        for entry in reads
        if entry["payload"]["ok"] is False
    ] == ["STALE_PROJECT_MERGE_QUEUE_CATALOG"]
