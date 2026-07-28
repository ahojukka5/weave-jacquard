from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "merge-candidate-test-runs"
PROGRAM_V2 = """(program
  (name \"merge-candidate-test-runs\")
  (version \"0.2\"))
"""
REQUIRED_TOOLS = {
    "branch_create_at_revision",
    "branch_list",
    "branch_merge",
    "branch_merge_preview",
    "branch_merge_test_impact",
    "branch_merge_test_batch_run",
    "build_target_set",
    "merge_candidate_build_diagnostics_page",
    "merge_candidate_build_get",
    "merge_candidate_test_batch_get",
    "merge_candidate_test_output_page",
    "program_create",
    "program_import",
    "project_initialize",
    "sandbox_capabilities",
    "test_target_set",
    "tested_merge_attest",
    "tested_merge_attestation_get",
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

    output.write_text(
        "#!/bin/sh\nprintf 'done\\n'\nprintf 'warning\\n' >&2\nexit 7\n",
        encoding="utf-8",
    )
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
            "WEAVE_MERGE_BUILD_ROOT": str(tmp_path / "merge-builds"),
            "WEAVE_MERGE_TEST_RUN_ROOT": str(tmp_path / "merge-runs"),
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
        assert set(by_name) >= REQUIRED_TOOLS

        help_payload = await _call_payload(
            session,
            trace,
            "weave_help",
            topic="tested_merge_attestations",
        )
        assert help_payload["ok"] is True
        assert "branch_merge" in help_payload["help"]["workflow"]
        assert "does not prove" in help_payload["help"]["boundary"]

        capabilities = await _call(session, trace, "sandbox_capabilities")
        if capabilities["available"] is not True:
            pytest.skip(str(capabilities.get("probe_error") or capabilities))
        assert capabilities["policy"]["network"] == "deny"
        assert capabilities["policy"]["filesystem"] == "isolated"

        await _call(session, trace, "project_initialize", project=PROJECT)
        initial = _branch_heads(
            await _call(session, trace, "branch_list", project=PROJECT)
        )["main"]
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
        passing = await _call(
            session,
            trace,
            "test_target_set",
            project=PROJECT,
            branch="main",
            name="passing",
            build_target="application",
            expected_exit_code=7,
            expected_stdout="done\n",
            expected_stderr="warning\n",
            timeout_ms=2_000,
            max_memory_bytes=64 * 1024 * 1024,
            max_output_bytes=8_192,
            max_file_bytes=4_096,
            expected_revision_id=target["revision_id"],
        )
        failing = await _call(
            session,
            trace,
            "test_target_set",
            project=PROJECT,
            branch="main",
            name="failing",
            build_target="application",
            expected_exit_code=7,
            expected_stdout="incorrect\n",
            expected_stderr="warning\n",
            timeout_ms=2_000,
            max_memory_bytes=64 * 1024 * 1024,
            max_output_bytes=8_192,
            max_file_bytes=4_096,
            expected_revision_id=passing["revision_id"],
        )
        base_revision = failing["revision_id"]
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
        assert [item["name"] for item in plan["impacted_tests"]] == [
            "failing",
            "passing",
        ]
        execution = plan["candidate_execution"]
        assert execution["tool"] == "branch_merge_test_batch_run"
        assert execution["arguments"]["preview_id"] == preview["preview_id"]

        qualification = await _call(
            session,
            trace,
            execution["tool"],
            **execution["arguments"],
        )
        assert qualification["status"] == "failed"
        assert qualification["all_passed"] is False
        assert qualification["passed_test_count"] == 1
        assert qualification["failed_test_count"] == 1
        assert qualification["error_test_count"] == 0
        assert qualification["subject"]["committed_revision_id"] is None
        assert qualification["subject"]["preview_id"] == preview["preview_id"]
        assert qualification["subject"]["merged_root_hash"] == preview["merged_root_hash"]
        assert qualification["heads_unchanged_at_completion"] is True
        assert qualification["publication_candidate_current_at_completion"] is True
        assert [item["outcome"] for item in qualification["results"]] == [
            "failed",
            "passed",
        ]
        assert len(qualification["builds"]) == 1

        repeated = await _call(
            session,
            trace,
            "merge_candidate_test_batch_get",
            qualification_id=qualification["qualification_id"],
        )
        assert repeated["manifest_sha256"] == qualification["manifest_sha256"]
        assert repeated["results"] == qualification["results"]

        stdout_page = await _call(
            session,
            trace,
            "merge_candidate_test_output_page",
            qualification_id=qualification["qualification_id"],
            test_target="passing",
            stream="stdout",
            max_bytes=2,
        )
        assert stdout_page["utf8_text"] == "do"
        assert stdout_page["next_byte"] == 2

        build_id = qualification["builds"][0]["build_id"]
        build = await _call(
            session,
            trace,
            "merge_candidate_build_get",
            build_id=build_id,
        )
        assert build["status"] == "succeeded"
        assert build["subject"] == qualification["subject"]
        assert "artifact_paths" not in build
        assert "build_directory" not in build
        assert "command" not in build
        diagnostics = await _call(
            session,
            trace,
            "merge_candidate_build_diagnostics_page",
            build_id=build_id,
            limit=10,
        )
        assert diagnostics["status"] == "succeeded"
        assert diagnostics["total_diagnostic_count"] == 0
        assert diagnostics["returned_count"] == 0

        heads_after_tests = _branch_heads(
            await _call(session, trace, "branch_list", project=PROJECT)
        )
        assert heads_after_tests == heads_before

        merged = await _call(
            session,
            trace,
            "branch_merge",
            project=PROJECT,
            target_branch="main",
            source_branch="feature",
            preview_id=preview["preview_id"],
        )
        heads_after_merge = _branch_heads(
            await _call(session, trace, "branch_list", project=PROJECT)
        )
        assert heads_after_merge == {
            "feature": feature["revision_id"],
            "main": merged["revision_id"],
        }

        attestation = await _call(
            session,
            trace,
            "tested_merge_attest",
            qualification_id=qualification["qualification_id"],
            merged_revision_id=merged["revision_id"],
        )
        assert attestation["state_identity_verified"] is True
        assert attestation["qualification_status"] == "failed"
        assert attestation["all_selected_tests_passed"] is False
        assert attestation["subject"] == qualification["subject"]
        assert attestation["merged_revision"] == {
            "revision_id": merged["revision_id"],
            "project": PROJECT,
            "parent1_revision_id": base_revision,
            "parent2_revision_id": feature["revision_id"],
            "root_hash": preview["merged_root_hash"],
        }
        assert attestation["interpretation"]["qualified_state_was_committed_exactly"] is True
        assert attestation["interpretation"]["all_selected_tests_passed"] is False
        assert attestation["interpretation"]["claims_policy_admission"] is False

        reread_attestation = await _call(
            session,
            trace,
            "tested_merge_attestation_get",
            attestation_id=attestation["attestation_id"],
        )
        assert reread_attestation["manifest_sha256"] == attestation["manifest_sha256"]
        assert reread_attestation["merged_revision"] == attestation["merged_revision"]

    return trace


@pytest.mark.real_mcp
@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap not installed")
def test_real_mcp_executes_virtual_merge_candidate_tests(tmp_path: Path) -> None:
    compiler = _fake_compiler(tmp_path / "weavec")
    trace = asyncio.run(_run(tmp_path, compiler))
    (tmp_path / "merge-candidate-test-runs-trace.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    attestation_trace = [
        entry
        for entry in trace
        if entry["tool"]
        in {
            "branch_merge",
            "tested_merge_attest",
            "tested_merge_attestation_get",
        }
        or (
            entry["tool"] == "weave_help"
            and entry["arguments"].get("topic") == "tested_merge_attestations"
        )
    ]
    (tmp_path / "tested-merge-attestation-trace.json").write_text(
        json.dumps(attestation_trace, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    execution_calls = [
        entry for entry in trace if entry["tool"] == "branch_merge_test_batch_run"
    ]
    assert len(execution_calls) == 1
    result = execution_calls[0]["payload"]["result"]
    assert result["status"] == "failed"
    assert result["heads_unchanged_at_completion"] is True
    attestations = [entry for entry in trace if entry["tool"] == "tested_merge_attest"]
    assert len(attestations) == 1
    assert attestations[0]["payload"]["result"]["state_identity_verified"] is True
    assert attestations[0]["payload"]["result"]["all_selected_tests_passed"] is False
