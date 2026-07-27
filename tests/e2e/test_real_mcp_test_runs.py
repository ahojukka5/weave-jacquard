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
PROJECT = "sandboxed-test-runs"
RUN_TOOLS = {
    "sandbox_capabilities",
    "test_run",
    "test_run_get",
    "test_run_output_page",
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
        assert set(by_name) >= RUN_TOOLS

        help_payload = await _call_payload(
            session,
            trace,
            "weave_help",
            topic="test_runs",
        )
        assert help_payload["ok"] is True
        assert "never silently substitutes" in help_payload["help"]["probe"]

        capabilities = await _call(session, trace, "sandbox_capabilities")
        assert capabilities["available"] is True, capabilities
        assert capabilities["policy"]["network"] == "deny"
        assert capabilities["policy"]["filesystem"] == "isolated"
        assert capabilities["policy"]["seccomp"] is False

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
            program_name="sandboxed-test-runs",
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
        passing_definition = await _call(
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
        head_before_run = _main_head(
            await _call(session, trace, "branch_list", project=PROJECT)
        )
        assert head_before_run == passing_definition["revision_id"]

        passed = await _call(
            session,
            trace,
            "test_run",
            project=PROJECT,
            test_target="passing",
            branch="main",
            revision_id=passing_definition["revision_id"],
        )
        assert passed["passed"] is True
        assert passed["status"] == "passed"
        assert passed["definition_hash"] == passing_definition["definition_hash"]
        assert passed["sandbox"]["policy_hash"] == capabilities["policy_hash"]
        assert "artifact_paths" not in passed
        assert _main_head(
            await _call(session, trace, "branch_list", project=PROJECT)
        ) == head_before_run

        resolved = await _call(
            session,
            trace,
            "test_run_get",
            run_id=passed["run_id"],
        )
        assert resolved["manifest_sha256"] == passed["manifest_sha256"]
        assert "artifact_paths" not in resolved
        stdout_page = await _call(
            session,
            trace,
            "test_run_output_page",
            run_id=passed["run_id"],
            stream="stdout",
            max_bytes=2,
        )
        assert stdout_page["utf8_text"] == "do"
        assert stdout_page["next_byte"] == 2

        failing_definition = await _call(
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
            expected_revision_id=head_before_run,
        )
        failed = await _call(
            session,
            trace,
            "test_run",
            project=PROJECT,
            test_target="failing",
            revision_id=failing_definition["revision_id"],
        )
        assert failed["passed"] is False
        assert failed["status"] == "failed"
        assert failed["assertions"]["stdout"] is False
        assert failed["assertions"]["exit_code"] is True
        assert "artifact_paths" not in failed

    return trace


def _verify_retained_runs(tmp_path: Path) -> None:
    run_directories = sorted(path for path in (tmp_path / "runs").iterdir() if path.is_dir())
    assert len(run_directories) == 2
    statuses: list[str] = []
    for directory in run_directories:
        manifest = json.loads((directory / "run-manifest.json").read_text(encoding="utf-8"))
        assert manifest["run_id"] == directory.name
        assert manifest["format"] == "weave-test-run-manifest-v1"
        assert (directory / "stdout.bin").read_bytes() == b"done\n"
        assert (directory / "stderr.bin").read_bytes() == b"warning\n"
        statuses.append(manifest["status"])
    assert sorted(statuses) == ["failed", "passed"]


@pytest.mark.real_mcp
@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap not installed")
def test_real_mcp_runs_behavioral_tests_in_strict_sandbox(tmp_path: Path) -> None:
    compiler = _fake_compiler(tmp_path / "weavec")
    trace = asyncio.run(_run(tmp_path, compiler))
    _verify_retained_runs(tmp_path)
    (tmp_path / "test-runs-trace.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    run_calls = [entry for entry in trace if entry["tool"] == "test_run"]
    assert [entry["payload"]["result"]["passed"] for entry in run_calls] == [
        True,
        False,
    ]
