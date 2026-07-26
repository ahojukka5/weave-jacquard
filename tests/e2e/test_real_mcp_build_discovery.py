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
PROJECT = "build-discovery"
DOCUMENT = "main.weave"

PROGRAM_40 = """(program
  (name "build-discovery")
  (version "0.1")
  (entry main
    (params)
    (returns i32)
    (do (return (const_i32 40)))))
"""
PROGRAM_41 = PROGRAM_40.replace('(version "0.1")', '(version "0.2")').replace(
    "const_i32 40", "const_i32 41"
)
PROGRAM_INVALID = PROGRAM_41.replace("const_i32 41", "unknown_form 0")
PROGRAM_42 = PROGRAM_40.replace('name "build-discovery"', 'name "foreign"').replace(
    "const_i32 40", "const_i32 42"
)


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
    name: str,
    **arguments: Any,
) -> dict[str, Any]:
    response = await session.call_tool(name, arguments=arguments)
    payload = _payload(response)
    trace.append({"tool": name, "arguments": arguments, "payload": payload})
    assert _attribute(response, "is_error", "isError") is not True, payload
    return payload


async def _call(
    session: ClientSession,
    trace: list[dict[str, Any]],
    name: str,
    **arguments: Any,
) -> Any:
    payload = await _call_payload(session, trace, name, **arguments)
    assert payload.get("ok") is True, payload
    return payload["result"]


async def _call_error(
    session: ClientSession,
    trace: list[dict[str, Any]],
    name: str,
    **arguments: Any,
) -> dict[str, Any]:
    payload = await _call_payload(session, trace, name, **arguments)
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


def _corrupt_candidate(build_root: Path, build_id: str) -> None:
    directory = build_root / build_id
    directory.mkdir(parents=True)
    (directory / "manifest.json").write_text("{}\n", encoding="utf-8")


async def _build(
    session: ClientSession,
    trace: list[dict[str, Any]],
    *,
    project: str,
    source: str,
    replace: bool,
) -> dict[str, Any]:
    imported = await _call(
        session,
        trace,
        "program_import",
        project=project,
        branch="main",
        document=DOCUMENT,
        source=source,
        replace=replace,
    )
    build = await _call(
        session,
        trace,
        "program_build",
        project=project,
        branch="main",
        document=DOCUMENT,
    )
    assert build["revision_id"] == imported["revision_id"]
    return build


async def _run(tmp_path: Path, compiler: Path) -> list[dict[str, Any]]:
    trace: list[dict[str, Any]] = []
    build_root = tmp_path / "builds"
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
        assert "build_list_page" in {tool.name for tool in tools.tools}

        await _call(session, trace, "project_initialize", project=PROJECT)
        succeeded_40 = await _build(
            session,
            trace,
            project=PROJECT,
            source=PROGRAM_40,
            replace=False,
        )
        succeeded_41 = await _build(
            session,
            trace,
            project=PROJECT,
            source=PROGRAM_41,
            replace=True,
        )
        failed = await _build(
            session,
            trace,
            project=PROJECT,
            source=PROGRAM_INVALID,
            replace=True,
        )
        assert succeeded_40["status"] == "succeeded"
        assert succeeded_41["status"] == "succeeded"
        assert failed["status"] == "failed"

        await _call(session, trace, "project_initialize", project="foreign-project")
        foreign = await _build(
            session,
            trace,
            project="foreign-project",
            source=PROGRAM_42,
            replace=False,
        )
        assert foreign["status"] == "succeeded"

        occupied = {
            succeeded_40["build_id"],
            succeeded_41["build_id"],
            failed["build_id"],
            foreign["build_id"],
        }
        corrupt_id = "f" * 32
        assert corrupt_id not in occupied
        _corrupt_candidate(build_root, corrupt_id)

        pages: list[dict[str, Any]] = []
        catalog_id: str | None = None
        start_after: str | None = None
        while True:
            page = await _call(
                session,
                trace,
                "build_list_page",
                project=PROJECT,
                catalog_id=catalog_id,
                start_after_build_id=start_after,
                limit=1,
            )
            pages.append(page)
            catalog_id = str(page["catalog_id"])
            if not page["has_more"]:
                break
            start_after = str(page["next_after_build_id"])

        discovered = [build for page in pages for build in page["builds"]]
        rejected = [item for page in pages for item in page["rejected_builds"]]
        discovered_ids = {build["build_id"] for build in discovered}
        assert pages[0]["catalog_build_count"] == 5
        assert sum(page["scanned_count"] for page in pages) == 5
        assert len(discovered) == 3
        assert discovered_ids == {
            succeeded_40["build_id"],
            succeeded_41["build_id"],
            failed["build_id"],
        }
        assert sum(page["filtered_count"] for page in pages) == 1
        assert rejected == [
            {"build_id": corrupt_id, "code": "INVALID_BUILD_MANIFEST"}
        ]
        assert all("artifact_paths" not in build for build in discovered)
        assert all("build_directory" not in build for build in discovered)

        failed_page = await _call(
            session,
            trace,
            "build_list_page",
            project=PROJECT,
            status="failed",
            revision_id=failed["revision_id"],
            document=DOCUMENT,
            target="native",
            limit=200,
        )
        assert failed_page["returned_count"] == 1
        assert failed_page["builds"][0]["build_id"] == failed["build_id"]
        assert failed_page["builds"][0]["executable_available"] is False

        recovered = await _call(
            session,
            trace,
            "build_get",
            build_id=succeeded_41["build_id"],
        )
        assert recovered["project"] == PROJECT
        assert recovered["revision_id"] == succeeded_41["revision_id"]
        assert recovered["status"] == "succeeded"

        added_id = "e" * 32
        assert added_id not in occupied and added_id != corrupt_id
        _corrupt_candidate(build_root, added_id)
        stale = await _call_error(
            session,
            trace,
            "build_list_page",
            project=PROJECT,
            catalog_id=catalog_id,
            start_after_build_id=start_after,
            limit=1,
        )
        assert stale["code"] == "STALE_BUILD_CATALOG"

    (tmp_path / "build-discovery-trace.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return trace


@pytest.mark.real_mcp
@pytest.mark.real_e2e
def test_real_mcp_discovers_verified_stored_builds(tmp_path: Path) -> None:
    configured = os.environ.get("WEAVEC_BIN")
    if not configured:
        pytest.skip("WEAVEC_BIN is required for build discovery qualification")
    compiler = Path(configured).resolve()
    assert compiler.is_file()

    trace = asyncio.run(_run(tmp_path, compiler))
    pages = [entry for entry in trace if entry["tool"] == "build_list_page"]
    assert len(pages) == 7
    catalog_pages = pages[:5]
    assert sum(entry["payload"]["result"]["returned_count"] for entry in catalog_pages) == 3
    assert sum(entry["payload"]["result"]["rejected_count"] for entry in catalog_pages) == 1
    assert pages[-1]["payload"]["error"]["code"] == "STALE_BUILD_CATALOG"
