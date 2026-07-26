from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[2]
DOCUMENT = "main.weave"


@dataclass(frozen=True)
class Atom:
    kind: str
    value: Any


@dataclass(frozen=True)
class Form:
    head: str
    children: tuple[NodeSpec, ...] = ()


NodeSpec = Atom | Form


@dataclass(frozen=True)
class ProgramCase:
    name: str
    expected_exit: int
    forms: tuple[Form, ...]
    source_fragments: tuple[str, ...]
    llvm_fragments: tuple[str, ...]


def form(head: str, *children: NodeSpec) -> Form:
    return Form(head, tuple(children))


def sym(value: str) -> Atom:
    return Atom("symbol", value)


def integer(value: int) -> Atom:
    return Atom("integer", value)


def _entry(*body: NodeSpec) -> Form:
    return form(
        "entry",
        sym("main"),
        form("params"),
        form("returns", sym("i32")),
        form("do", *body),
    )


def _while_accumulator() -> ProgramCase:
    return ProgramCase(
        name="while-accumulator",
        expected_exit=42,
        forms=(
            _entry(
                form("let", sym("i"), sym("i32"), form("const_i32", integer(0))),
                form("let", sym("sum"), sym("i32"), form("const_i32", integer(0))),
                form(
                    "while",
                    form(
                        "condition",
                        form(
                            "lt_i32",
                            form("local_get", sym("i")),
                            form("const_i32", integer(7)),
                        ),
                    ),
                    form(
                        "do",
                        form(
                            "set",
                            sym("sum"),
                            form(
                                "add_i32",
                                form("local_get", sym("sum")),
                                form("const_i32", integer(6)),
                            ),
                        ),
                        form(
                            "set",
                            sym("i"),
                            form(
                                "add_i32",
                                form("local_get", sym("i")),
                                form("const_i32", integer(1)),
                            ),
                        ),
                    ),
                ),
                form("return", form("local_get", sym("sum"))),
            ),
        ),
        source_fragments=("(while", "(set sum", "(local_get sum)"),
        llvm_fragments=("phi i32", "br i1", "add i32"),
    )


def _multi_function_chain() -> ProgramCase:
    return ProgramCase(
        name="multi-function-chain",
        expected_exit=35,
        forms=(
            form("entry", sym("main")),
            form(
                "fn",
                sym("calculate"),
                form("params", form("x", sym("i32"))),
                form("returns", sym("i32")),
                form(
                    "do",
                    form(
                        "return",
                        form(
                            "add_i32",
                            form(
                                "call_i32",
                                sym("helper_double"),
                                form("param_get", sym("x")),
                            ),
                            form(
                                "call_i32",
                                sym("helper_square"),
                                form("param_get", sym("x")),
                            ),
                        ),
                    ),
                ),
            ),
            form(
                "fn",
                sym("helper_double"),
                form("params", form("n", sym("i32"))),
                form("returns", sym("i32")),
                form(
                    "do",
                    form(
                        "return",
                        form(
                            "mul_i32",
                            form("param_get", sym("n")),
                            form("const_i32", integer(2)),
                        ),
                    ),
                ),
            ),
            form(
                "fn",
                sym("helper_square"),
                form("params", form("n", sym("i32"))),
                form("returns", sym("i32")),
                form(
                    "do",
                    form(
                        "return",
                        form(
                            "mul_i32",
                            form("param_get", sym("n")),
                            form("param_get", sym("n")),
                        ),
                    ),
                ),
            ),
            form(
                "fn",
                sym("main"),
                form("params"),
                form("returns", sym("i32")),
                form(
                    "do",
                    form(
                        "return",
                        form(
                            "call_i32",
                            sym("calculate"),
                            form("const_i32", integer(5)),
                        ),
                    ),
                ),
            ),
        ),
        source_fragments=(
            "(fn calculate",
            "(call_i32 helper_double",
            "(call_i32 helper_square",
        ),
        llvm_fragments=(
            "define i32 @calculate(i32 %x)",
            "call i32 @helper_double(i32 %x)",
            "call i32 @helper_square(i32 %x)",
        ),
    )


def _memory_flow() -> ProgramCase:
    increment_i = form(
        "set",
        sym("i"),
        form(
            "add_i32",
            form("local_get", sym("i")),
            form("const_i32", integer(1)),
        ),
    )
    address = form(
        "ptr_add",
        form("param_get", sym("buffer")),
        form(
            "mul_i64",
            form("cast_i32_to_i64", form("local_get", sym("i"))),
            form("const_i64", integer(4)),
        ),
    )
    return ProgramCase(
        name="memory-flow",
        expected_exit=100,
        forms=(
            form("entry", sym("main")),
            form(
                "fn",
                sym("write_values"),
                form(
                    "params",
                    form("buffer", sym("ptr")),
                    form("count", sym("i32")),
                ),
                form("returns", sym("void")),
                form(
                    "do",
                    form("let", sym("i"), sym("i32"), form("const_i32", integer(0))),
                    form(
                        "while",
                        form(
                            "condition",
                            form(
                                "lt_i32",
                                form("local_get", sym("i")),
                                form("param_get", sym("count")),
                            ),
                        ),
                        form(
                            "do",
                            form(
                                "store_i32",
                                address,
                                form(
                                    "mul_i32",
                                    form("local_get", sym("i")),
                                    form("const_i32", integer(10)),
                                ),
                            ),
                            increment_i,
                        ),
                    ),
                    form("return_void"),
                ),
            ),
            form(
                "fn",
                sym("sum_values"),
                form(
                    "params",
                    form("buffer", sym("ptr")),
                    form("count", sym("i32")),
                ),
                form("returns", sym("i32")),
                form(
                    "do",
                    form(
                        "let",
                        sym("sum"),
                        sym("i32"),
                        form("const_i32", integer(0)),
                    ),
                    form("let", sym("i"), sym("i32"), form("const_i32", integer(0))),
                    form(
                        "while",
                        form(
                            "condition",
                            form(
                                "lt_i32",
                                form("local_get", sym("i")),
                                form("param_get", sym("count")),
                            ),
                        ),
                        form(
                            "do",
                            form(
                                "set",
                                sym("sum"),
                                form(
                                    "add_i32",
                                    form("local_get", sym("sum")),
                                    form("load_i32", address),
                                ),
                            ),
                            increment_i,
                        ),
                    ),
                    form("return", form("local_get", sym("sum"))),
                ),
            ),
            form(
                "fn",
                sym("main"),
                form("params"),
                form("returns", sym("i32")),
                form(
                    "do",
                    form(
                        "let",
                        sym("buffer"),
                        sym("ptr"),
                        form("call_ptr", sym("malloc"), form("const_i64", integer(20))),
                    ),
                    form(
                        "call_void",
                        sym("write_values"),
                        form("local_get", sym("buffer")),
                        form("const_i32", integer(5)),
                    ),
                    form(
                        "let",
                        sym("result"),
                        sym("i32"),
                        form(
                            "call_i32",
                            sym("sum_values"),
                            form("local_get", sym("buffer")),
                            form("const_i32", integer(5)),
                        ),
                    ),
                    form("call_void", sym("free"), form("local_get", sym("buffer"))),
                    form("return", form("local_get", sym("result"))),
                ),
            ),
        ),
        source_fragments=("(call_ptr malloc", "(store_i32", "(load_i32"),
        llvm_fragments=(
            "declare ptr @malloc(i64)",
            "call void @write_values(ptr",
            "getelementptr i8",
            "load i32, ptr",
        ),
    )


CASES = (_while_accumulator(), _multi_function_chain(), _memory_flow())


def _attribute(value: Any, snake_case: str, camel_case: str) -> Any:
    result = getattr(value, snake_case, None)
    return result if result is not None else getattr(value, camel_case, None)


def _payload(result: Any) -> dict[str, Any]:
    structured = _attribute(result, "structured_content", "structuredContent")
    if isinstance(structured, dict):
        return structured
    for block in getattr(result, "content", []):
        text = getattr(block, "text", None)
        if not isinstance(text, str):
            continue
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise AssertionError(f"tool result did not contain a JSON object: {result!r}")


def _server_environment(tmp_path: Path, compiler: Path) -> dict[str, str]:
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


async def _call(
    session: ClientSession,
    trace: list[dict[str, Any]],
    name: str,
    arguments: dict[str, Any],
) -> Any:
    response = await session.call_tool(name, arguments=arguments)
    payload = _payload(response)
    trace.append({"tool": name, "arguments": arguments, "payload": payload})
    assert _attribute(response, "is_error", "isError") is not True, payload
    assert payload.get("ok") is True, payload
    return payload.get("result")


async def _append_node(
    session: ClientSession,
    trace: list[dict[str, Any]],
    *,
    project: str,
    parent_id: str,
    node: NodeSpec,
) -> str:
    if isinstance(node, Atom):
        created = await _call(
            session,
            trace,
            "node_add_atom",
            {
                "project": project,
                "branch": "main",
                "document": DOCUMENT,
                "parent_id": parent_id,
                "kind": node.kind,
                "value": node.value,
            },
        )
        return str(created["node_id"])

    created = await _call(
        session,
        trace,
        "node_create_form",
        {
            "project": project,
            "branch": "main",
            "document": DOCUMENT,
            "parent_id": parent_id,
            "head": node.head,
        },
    )
    node_id = str(created["node_id"])
    for child in node.children:
        await _append_node(
            session,
            trace,
            project=project,
            parent_id=node_id,
            node=child,
        )
    return node_id


def _node_count(node: NodeSpec) -> int:
    if isinstance(node, Atom):
        return 1
    return 1 + sum(_node_count(child) for child in node.children)


def _run_checked(command: list[str]) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    return completed


async def _run_case(case: ProgramCase, tmp_path: Path, compiler: Path) -> dict[str, Any]:
    trace: list[dict[str, Any]] = []
    project = f"stress-{case.name}"
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "weave_jacquard.mcp_build"],
        env=_server_environment(tmp_path, compiler),
        cwd=str(ROOT),
    )

    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        initialized = await session.initialize()
        server_info = _attribute(initialized, "server_info", "serverInfo")
        assert server_info is not None
        assert server_info.name == "weave-mcp"

        await _call(session, trace, "project_initialize", {"project": project})
        program = await _call(
            session,
            trace,
            "program_create",
            {
                "project": project,
                "branch": "main",
                "document": DOCUMENT,
                "program_name": case.name,
            },
        )
        root_id = str(program["node_id"])
        for node in case.forms:
            await _append_node(
                session,
                trace,
                project=project,
                parent_id=root_id,
                node=node,
            )

        rendered = await _call(
            session,
            trace,
            "program_render",
            {
                "project": project,
                "branch": "main",
                "document": DOCUMENT,
                "annotated": False,
            },
        )
        source = str(rendered["source"])
        assert "@n_" not in source
        for fragment in case.source_fragments:
            assert fragment in source

        validated = await _call(
            session,
            trace,
            "program_validate",
            {"project": project, "branch": "main", "document": DOCUMENT},
        )
        assert validated["available"] is True
        assert validated["valid"] is True
        assert str(validated["wir"]).strip()

        built = await _call(
            session,
            trace,
            "program_build",
            {"project": project, "branch": "main", "document": DOCUMENT},
        )
        assert built["status"] == "succeeded"
        assert built["compiler_manifest_protocol_valid"] is True
        assert built["compiler_diagnostics_protocol_valid"] is True

        inspected = await _call(
            session,
            trace,
            "build_get",
            {"build_id": built["build_id"]},
        )
        source_path = Path(inspected["artifact_paths"]["source"])
        executable = Path(inspected["artifact_paths"]["executable"])
        assert source_path.read_text(encoding="utf-8") == source + "\n"

        history = await _call(
            session,
            trace,
            "branch_history",
            {"project": project, "branch": "main"},
        )

    executed = subprocess.run(
        [str(executable)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert executed.returncode == case.expected_exit, {
        "expected": case.expected_exit,
        "actual": executed.returncode,
        "stdout": executed.stdout,
        "stderr": executed.stderr,
    }

    evidence = tmp_path / "evidence" / case.name
    evidence.mkdir(parents=True)
    canonical_path = evidence / "main.weave"
    canonical_path.write_text(source + "\n", encoding="utf-8")
    wir_path = evidence / "program.wir"
    llvm_path = evidence / "program.ll"
    bitcode_path = evidence / "program.bc"
    _run_checked([str(compiler), "--frontend", str(wir_path), str(canonical_path)])
    _run_checked([str(compiler), "--backend", str(wir_path), str(llvm_path)])
    llvm_as = shutil.which("llvm-as")
    assert llvm_as is not None
    _run_checked([llvm_as, str(llvm_path), "-o", str(bitcode_path)])

    llvm = llvm_path.read_text(encoding="utf-8")
    assert "define i32 @main" in llvm
    for fragment in case.llvm_fragments:
        assert fragment in llvm

    summary = {
        "case": case.name,
        "expected_exit": case.expected_exit,
        "actual_exit": executed.returncode,
        "node_count": sum(_node_count(node) for node in case.forms),
        "tool_calls": len(trace),
        "reachable_revisions": len(history),
        "source_bytes": canonical_path.stat().st_size,
        "wir_bytes": wir_path.stat().st_size,
        "llvm_bytes": llvm_path.stat().st_size,
        "bitcode_bytes": bitcode_path.stat().st_size,
        "build_id": built["build_id"],
    }
    (evidence / "qualification-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (evidence / "mcp-trace.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def _configured_compiler() -> Path:
    configured = os.environ.get("WEAVEC_BIN")
    if not configured:
        pytest.skip("set WEAVEC_BIN to an executable final weavec")
    compiler = Path(configured).expanduser().resolve()
    if not compiler.is_file() or not os.access(compiler, os.X_OK):
        pytest.skip(f"WEAVEC_BIN is not executable: {compiler}")
    if os.name == "nt":
        pytest.skip("native execution qualification is currently POSIX-only")
    return compiler


@pytest.mark.real_mcp
@pytest.mark.real_e2e
@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_real_mcp_complex_program_matrix(
    case: ProgramCase,
    tmp_path: Path,
) -> None:
    summary = asyncio.run(_run_case(case, tmp_path, _configured_compiler()))
    assert summary["actual_exit"] == case.expected_exit
    assert summary["node_count"] >= 20
    assert summary["tool_calls"] > summary["node_count"]
    assert summary["reachable_revisions"] >= summary["node_count"] + 1
