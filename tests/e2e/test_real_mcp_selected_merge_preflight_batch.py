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
PROJECT = "selected-merge-preflight-batch"
TOOL = "selected_merge_preflight_batch"

MAIN_SOURCE = """(program
  (name "batch-demo")
  (version "0.1")
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

ORPHAN_SOURCE = """(program
  (name "orphan")
  (version "0.1")
  (entry main)
  (fn main
    (params)
    (returns i32)
    (do (return (const_i32 7))))
)
"""


def _fake_compiler(path: Path) -> Path:
    path.write_text(
        r"""#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def manifest(source: Path, output: Path, status: str, phase: str) -> dict[str, object]:
    return {
        "format": "weavec-build-manifest-v1",
        "status": status,
        "phase": phase,
        "target": "x86_64-unknown-linux-gnu",
        "compiler": str(Path(sys.argv[0]).resolve()),
        "runtime": "/opt/weavec/libweave-runtime.a",
        "codegen": "clang",
        "linker": "clang",
        "output": str(output),
        "sources": [str(source)],
    }


def diagnostics(status: str, phase: str, exit_code: int) -> dict[str, object]:
    return {
        "format": "weavec-diagnostics-v1",
        "status": status,
        "phase": phase,
        "exit_code": exit_code,
        "raw_exit_code": exit_code,
        "diagnostics": [],
    }


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def frontend() -> int:
    if len(sys.argv) < 4:
        return 2
    wir_path = Path(sys.argv[2])
    source_paths = [Path(value) for value in sys.argv[3:]]
    text = "\n".join(path.read_text(encoding="utf-8") for path in source_paths)
    if "force-build-failure" in text:
        print("selected batch fake frontend failure", file=sys.stderr)
        return 11
    wir_path.write_text(
        "module selected_merge_preflight_batch\n",
        encoding="utf-8",
    )
    return 0


def build() -> int:
    if len(sys.argv) < 8:
        return 2
    source = Path(sys.argv[2])
    output = Path(sys.argv[sys.argv.index("-o") + 1])
    manifest_path = Path(sys.argv[sys.argv.index("--manifest-json") + 1])
    diagnostics_path = Path(sys.argv[sys.argv.index("--diagnostics-json") + 1])
    text = source.read_text(encoding="utf-8")
    if "force-build-failure" in text:
        write_json(manifest_path, manifest(source, output, "failed", "backend"))
        write_json(diagnostics_path, diagnostics("failed", "backend", 11))
        print("selected batch fake compiler failure", file=sys.stderr)
        return 11
    output.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    os.chmod(output, 0o755)
    write_json(manifest_path, manifest(source, output, "succeeded", "complete"))
    write_json(diagnostics_path, diagnostics("succeeded", "complete", 0))
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--frontend":
        return frontend()
    if len(sys.argv) > 1 and sys.argv[1] == "build":
        return build()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
""",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


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


def _schema(tool: Any) -> dict[str, Any]:
    value = _attribute(tool, "input_schema", "inputSchema")
    assert isinstance(value, dict), tool
    return value


async def _run(
    tmp_path: Path,
    compiler: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
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
        by_name = {tool.name: tool for tool in tools.tools}
        assert {
            TOOL,
            "project_merge_impact_queue_page",
            "branch_merge_preflight",
            "branch_merge",
        } <= set(by_name)
        properties = _schema(by_name[TOOL]).get("properties")
        assert isinstance(properties, dict)
        assert {
            "target_branch",
            "sources",
            "catalog_id",
            "allow_uncovered_sources",
            "validation_result_limit",
            "document_limit",
        } <= set(properties)

        await _call(session, trace, "project_initialize", project=PROJECT)
        imported = await _call(
            session,
            trace,
            "program_import",
            project=PROJECT,
            branch="main",
            document="main.weave",
            source=MAIN_SOURCE,
        )
        orphan = await _call(
            session,
            trace,
            "program_import",
            project=PROJECT,
            branch="main",
            document="orphan.weave",
            source=ORPHAN_SOURCE,
            expected_revision_id=imported["revision_id"],
        )
        one = await _call(
            session,
            trace,
            "node_find",
            project=PROJECT,
            branch="main",
            document="main.weave",
            kind="integer",
            value=1,
        )
        two = await _call(
            session,
            trace,
            "node_find",
            project=PROJECT,
            branch="main",
            document="main.weave",
            kind="integer",
            value=2,
        )
        seven = await _call(
            session,
            trace,
            "node_find",
            project=PROJECT,
            branch="main",
            document="orphan.weave",
            kind="integer",
            value=7,
        )
        names = await _call(
            session,
            trace,
            "node_find",
            project=PROJECT,
            branch="main",
            document="main.weave",
            kind="string",
            value="batch-demo",
        )
        assert len(one) == len(two) == len(seven) == len(names) == 1

        target_config = await _call(
            session,
            trace,
            "build_target_set",
            project=PROJECT,
            branch="main",
            name="application",
            document="main.weave",
            expected_revision_id=orphan["revision_id"],
        )
        policy = await _call(
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
        base_revision = str(policy["revision_id"])
        assert target_config["revision_id"] != base_revision
        for branch in ("conflict", "not-ready", "policy-error", "ready", "unselected"):
            await _call(
                session,
                trace,
                "branch_create_at_revision",
                project=PROJECT,
                branch=branch,
                revision_id=base_revision,
            )

        ready = await _call(
            session,
            trace,
            "node_set_atom",
            project=PROJECT,
            branch="ready",
            document="main.weave",
            node_id=two[0]["node_id"],
            value=20,
            expected_revision_id=base_revision,
        )
        not_ready = await _call(
            session,
            trace,
            "node_set_atom",
            project=PROJECT,
            branch="not-ready",
            document="main.weave",
            node_id=names[0]["node_id"],
            value="force-build-failure",
            expected_revision_id=base_revision,
        )
        conflict = await _call(
            session,
            trace,
            "node_set_atom",
            project=PROJECT,
            branch="conflict",
            document="main.weave",
            node_id=one[0]["node_id"],
            value=30,
            expected_revision_id=base_revision,
        )
        policy_error = await _call(
            session,
            trace,
            "node_set_atom",
            project=PROJECT,
            branch="policy-error",
            document="orphan.weave",
            node_id=seven[0]["node_id"],
            value=70,
            expected_revision_id=base_revision,
        )
        target = await _call(
            session,
            trace,
            "node_set_atom",
            project=PROJECT,
            branch="main",
            document="main.weave",
            node_id=one[0]["node_id"],
            value=10,
            expected_revision_id=base_revision,
        )

        queue = await _call(
            session,
            trace,
            "project_merge_impact_queue_page",
            project=PROJECT,
            target_branch="main",
            limit=5,
            checkpoint_scan_limit=20,
        )
        assert queue["source_catalog_count"] == 5
        catalog_id = str(queue["catalog_id"])
        heads_before = {
            item["name"]: item["head_revision_id"]
            for item in await _call(
                session,
                trace,
                "branch_list",
                project=PROJECT,
            )
        }

        batch = await _call(
            session,
            trace,
            TOOL,
            project=PROJECT,
            target_branch="main",
            sources=["ready", "not-ready", "conflict", "policy-error"],
            catalog_id=catalog_id,
            allow_uncovered_sources=["policy-error"],
            validation_result_limit=1,
            document_limit=1,
        )
        assert batch["selected_source_count"] == 4
        assert batch["completed_source_count"] == 2
        assert batch["error_source_count"] == 2
        assert batch["ready_source_count"] == 1
        assert batch["not_ready_source_count"] == 1
        assert [entry["source_branch"] for entry in batch["sources"]] == [
            "ready",
            "not-ready",
            "conflict",
            "policy-error",
        ]

        ready_result = batch["sources"][0]
        assert ready_result["source_head_revision_id"] == ready["revision_id"]
        assert ready_result["status"] == "completed"
        assert ready_result["ready_for_publication"] is True
        assert ready_result["passed_target_count"] == 1
        assert ready_result["failed_target_count"] == 0
        assert ready_result["returned_target_validation_count"] == 1
        assert ready_result["publication_arguments"]["preflight_id"] == ready_result["preflight_id"]

        failed_result = batch["sources"][1]
        assert failed_result["source_head_revision_id"] == not_ready["revision_id"]
        assert failed_result["status"] == "completed"
        assert failed_result["ready_for_publication"] is False
        assert failed_result["failed_target_count"] == 1
        assert failed_result["target_validations"][0]["valid"] is False

        conflict_result = batch["sources"][2]
        assert conflict_result["source_head_revision_id"] == conflict["revision_id"]
        assert conflict_result["status"] == "error"
        assert conflict_result["error"]["code"] == "MERGE_CONFLICT"

        policy_result = batch["sources"][3]
        assert policy_result["source_head_revision_id"] == policy_error["revision_id"]
        assert policy_result["status"] == "error"
        assert policy_result["error"]["code"] == "MERGE_POLICY_VIOLATION"
        assert policy_result["allow_uncovered_documents"] is True

        heads_after = {
            item["name"]: item["head_revision_id"]
            for item in await _call(
                session,
                trace,
                "branch_list",
                project=PROJECT,
            )
        }
        assert heads_after == heads_before

        advanced = await _call(
            session,
            trace,
            "program_create",
            project=PROJECT,
            branch="unselected",
            document="later.weave",
            program_name="later",
            expected_revision_id=base_revision,
        )
        stale = await _call_error(
            session,
            trace,
            TOOL,
            project=PROJECT,
            target_branch="main",
            sources=["ready"],
            catalog_id=catalog_id,
        )
        assert stale["code"] == "STALE_SELECTED_PREFLIGHT_CATALOG"

    return trace, {
        "policy": policy,
        "ready": ready,
        "not_ready": not_ready,
        "conflict": conflict,
        "policy_error": policy_error,
        "target": target,
        "advanced": advanced,
    }


def _verify_no_merge_publication(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "jacquard.db")
    connection.row_factory = sqlite3.Row
    try:
        merge_revisions = connection.execute(
            "SELECT COUNT(*) AS count FROM revisions WHERE parent2_id IS NOT NULL"
        ).fetchone()["count"]
        assert merge_revisions == 0
        batch_operations = connection.execute(
            """SELECT COUNT(*) AS count FROM operations
               WHERE operation_kind LIKE '%preflight_batch%'"""
        ).fetchone()["count"]
        assert batch_operations == 0
        branch_count = connection.execute("SELECT COUNT(*) AS count FROM branches").fetchone()[
            "count"
        ]
        assert branch_count == 6
    finally:
        connection.close()


@pytest.mark.real_mcp
def test_real_mcp_runs_selected_merge_preflight_batch(tmp_path: Path) -> None:
    compiler = _fake_compiler(tmp_path / "weavec")
    trace, state = asyncio.run(_run(tmp_path, compiler))
    _verify_no_merge_publication(tmp_path)
    (tmp_path / "selected-merge-preflight-batch-trace.json").write_text(
        json.dumps({"trace": trace, "state": state}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    batch_calls = [entry for entry in trace if entry["tool"] == TOOL]
    assert len(batch_calls) == 2
    assert batch_calls[0]["payload"]["ok"] is True
    assert batch_calls[1]["payload"]["error"]["code"] == ("STALE_SELECTED_PREFLIGHT_CATALOG")
