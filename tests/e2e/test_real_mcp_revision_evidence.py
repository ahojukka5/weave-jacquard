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
PROJECT = "revision-evidence"


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


def _main_head(branches: list[dict[str, Any]]) -> str:
    main = [branch for branch in branches if branch["name"] == "main"]
    assert len(main) == 1, branches
    return str(main[0]["head_revision_id"])


def _fake_compiler(path: Path) -> Path:
    path.write_text(
        r'''#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    if len(sys.argv) < 8 or sys.argv[1] != "build":
        return 2
    try:
        output_index = sys.argv.index("-o")
        manifest_index = sys.argv.index("--manifest-json")
        diagnostics_index = sys.argv.index("--diagnostics-json")
    except ValueError:
        return 2
    sources = [Path(value).resolve() for value in sys.argv[2:output_index]]
    output = Path(sys.argv[output_index + 1]).resolve()
    manifest = Path(sys.argv[manifest_index + 1]).resolve()
    diagnostics = Path(sys.argv[diagnostics_index + 1]).resolve()
    target = "x86_64-unknown-linux-gnu"
    if "--target" in sys.argv:
        target = sys.argv[sys.argv.index("--target") + 1]

    output.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    os.chmod(output, 0o755)
    write_json(
        manifest,
        {
            "format": "weavec-build-manifest-v1",
            "status": "succeeded",
            "phase": "complete",
            "target": target,
            "compiler": str(Path(sys.argv[0]).resolve()),
            "runtime": "/opt/weavec/libweave-runtime.a",
            "codegen": "clang",
            "linker": "clang",
            "output": str(output),
            "sources": [str(source) for source in sources],
        },
    )
    write_json(
        diagnostics,
        {
            "format": "weavec-diagnostics-v1",
            "status": "succeeded",
            "phase": "complete",
            "exit_code": 0,
            "raw_exit_code": 0,
            "diagnostics": [],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''',
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


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
            "WEAVE_TEST_RUN_ROOT": str(tmp_path / "runs"),
            "WEAVE_TEST_BATCH_ROOT": str(tmp_path / "batches"),
            "WEAVE_MERGE_TEST_RUN_ROOT": str(tmp_path / "qualifications"),
            "WEAVE_MERGE_ATTESTATION_ROOT": str(tmp_path / "attestations"),
            "WEAVEC_BIN": str(compiler),
        }
    )
    return environment


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
        by_name = {tool.name: tool for tool in tools.tools}
        assert "revision_evidence_page" in by_name
        schema = _attribute(
            by_name["revision_evidence_page"],
            "input_schema",
            "inputSchema",
        )
        assert {
            "project",
            "revision_id",
            "kind",
            "start_after_id",
            "catalog_id",
            "limit",
            "scan_limit",
        } <= set(schema["properties"])

        help_payload = await _call_payload(
            session,
            trace,
            "weave_help",
            topic="revision_evidence",
        )
        assert help_payload["ok"] is True
        assert "retained artifacts" in help_payload["help"]["boundary"]

        await _call(session, trace, "project_initialize", project=PROJECT)
        initial = _main_head(
            await _call(session, trace, "branch_list", project=PROJECT)
        )
        program = await _call(
            session,
            trace,
            "program_create",
            project=PROJECT,
            branch="main",
            document="main.weave",
            program_name="revision-evidence",
            expected_revision_id=initial,
        )
        head_before_build = _main_head(
            await _call(session, trace, "branch_list", project=PROJECT)
        )
        assert head_before_build == program["revision_id"]

        build = await _call(
            session,
            trace,
            "program_build",
            project=PROJECT,
            document="main.weave",
            revision_id=program["revision_id"],
        )
        assert build["status"] == "succeeded"
        assert _main_head(
            await _call(session, trace, "branch_list", project=PROJECT)
        ) == head_before_build

        page = await _call(
            session,
            trace,
            "revision_evidence_page",
            project=PROJECT,
            revision_id=program["revision_id"],
            kind="build",
            limit=10,
            scan_limit=10,
        )
        assert page["matched_evidence_count"] == 1
        assert page["has_more"] is False
        assert [node["kind"] for node in page["nodes"]] == ["revision", "build"]
        build_node = page["nodes"][1]
        assert build_node["evidence_id"] == build["build_id"]
        assert build_node["detail"] == {
            "tool": "build_get",
            "arguments": {"build_id": build["build_id"]},
        }
        assert page["edges"] == [
            {
                "from": f"build:{build['build_id']}",
                "relation": "built_from_revision",
                "to": f"revision:{program['revision_id']}",
            }
        ]
        assert page["interpretation"]["claims_complete_coverage"] is False
        assert "artifact_paths" not in str(page)
        assert str(tmp_path) not in str(page)

        replay = await _call(
            session,
            trace,
            "revision_evidence_page",
            project=PROJECT,
            revision_id=program["revision_id"],
            kind="build",
            catalog_id=page["catalog_id"],
            limit=10,
            scan_limit=10,
        )
        assert replay["page_id"] == page["page_id"]

        empty_runs = await _call(
            session,
            trace,
            "revision_evidence_page",
            project=PROJECT,
            revision_id=program["revision_id"],
            kind="test_run",
            limit=10,
            scan_limit=10,
        )
        assert empty_runs["matched_evidence_count"] == 0
        assert [node["kind"] for node in empty_runs["nodes"]] == ["revision"]
        assert _main_head(
            await _call(session, trace, "branch_list", project=PROJECT)
        ) == head_before_build

    return trace


@pytest.mark.real_mcp
def test_real_mcp_recovers_verified_build_evidence_by_revision(tmp_path: Path) -> None:
    compiler = _fake_compiler(tmp_path / "weavec")
    trace = asyncio.run(_run(tmp_path, compiler))
    (tmp_path / "revision-evidence-trace.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    evidence_calls = [
        entry for entry in trace if entry["tool"] == "revision_evidence_page"
    ]
    assert len(evidence_calls) == 3
    assert evidence_calls[0]["payload"]["result"]["matched_evidence_count"] == 1
    assert evidence_calls[-1]["payload"]["result"]["matched_evidence_count"] == 0
