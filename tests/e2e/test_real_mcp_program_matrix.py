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
    source_tokens: tuple[str, ...]
    llvm_fragments: tuple[str, ...]


def form(head: str, *children: NodeSpec) -> Form:
    return Form(head, tuple(children))


def sym(value: str) -> Atom:
    return Atom("symbol", value)


def integer(value: int) -> Atom:
    return Atom("integer", value)


def const_i32(value: int) -> Form:
    return form("const_i32", integer(value))


def const_i64(value: int) -> Form:
    return form("const_i64", integer(value))


def local(name: str) -> Form:
    return form("local_get", sym(name))


def param(name: str) -> Form:
    return form("param_get", sym(name))


def add(left: NodeSpec, right: NodeSpec) -> Form:
    return form("add_i32", left, right)


def increment(name: str) -> Form:
    return form("set", sym(name), add(local(name), const_i32(1)))


def entry(*body: NodeSpec) -> Form:
    return form(
        "entry",
        sym("main"),
        form("params"),
        form("returns", sym("i32")),
        form("do", *body),
    )


def while_accumulator() -> ProgramCase:
    return ProgramCase(
        name="while-accumulator",
        expected_exit=42,
        forms=(
            entry(
                form("let", sym("i"), sym("i32"), const_i32(0)),
                form("let", sym("sum"), sym("i32"), const_i32(0)),
                form(
                    "while",
                    form("condition", form("lt_i32", local("i"), const_i32(7))),
                    form(
                        "do",
                        form("set", sym("sum"), add(local("sum"), const_i32(6))),
                        increment("i"),
                    ),
                ),
                form("return", local("sum")),
            ),
        ),
        source_tokens=("while", "sum", "local_get"),
        llvm_fragments=("phi i32", "br i1", "add i32"),
    )


def multi_function_chain() -> ProgramCase:
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
                        add(
                            form("call_i32", sym("helper_double"), param("x")),
                            form("call_i32", sym("helper_square"), param("x")),
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
                        form("mul_i32", param("n"), const_i32(2)),
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
                        form("mul_i32", param("n"), param("n")),
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
                        form("call_i32", sym("calculate"), const_i32(5)),
                    ),
                ),
            ),
        ),
        source_tokens=("calculate", "helper_double", "helper_square"),
        llvm_fragments=(
            "define i32 @calculate(i32 %x)",
            "call i32 @helper_double(i32 %x)",
            "call i32 @helper_square(i32 %x)",
        ),
    )


def memory_address() -> Form:
    return form(
        "ptr_add",
        param("buffer"),
        form(
            "mul_i64",
            form("cast_i32_to_i64", local("i")),
            const_i64(4),
        ),
    )


def counted_loop(*body: NodeSpec) -> Form:
    return form(
        "while",
        form("condition", form("lt_i32", local("i"), param("count"))),
        form("do", *body, increment("i")),
    )


def memory_flow() -> ProgramCase:
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
                    form("let", sym("i"), sym("i32"), const_i32(0)),
                    counted_loop(
                        form(
                            "store_i32",
                            memory_address(),
                            form("mul_i32", local("i"), const_i32(10)),
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
                    form("let", sym("sum"), sym("i32"), const_i32(0)),
                    form("let", sym("i"), sym("i32"), const_i32(0)),
                    counted_loop(
                        form(
                            "set",
                            sym("sum"),
                            add(local("sum"), form("load_i32", memory_address())),
                        ),
                    ),
                    form("return", local("sum")),
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
                        form("call_ptr", sym("malloc"), const_i64(20)),
                    ),
                    form(
                        "call_void",
                        sym("write_values"),
                        local("buffer"),
                        const_i32(5),
                    ),
                    form(
                        "let",
                        sym("result"),
                        sym("i32"),
                        form(
                            "call_i32",
                            sym("sum_values"),
                            local("buffer"),
                            const_i32(5),
                        ),
                    ),
                    form("call_void", sym("free"), local("buffer")),
                    form("return", local("result")),
                ),
            ),
        ),
        source_tokens=("malloc", "store_i32", "load_i32", "free"),
        llvm_fragments=(
            "declare ptr @malloc(i64)",
            "call void @write_values(ptr",
            "getelementptr i8",
            "load i32, ptr",
        ),
    )


CASES = (while_accumulator(), multi_function_chain(), memory_flow())


def attribute(value: Any, snake_case: str, camel_case: str) -> Any:
    result = getattr(value, snake_case, None)
    return result if result is not None else getattr(value, camel_case, None)


def payload(result: Any) -> dict[str, Any]:
    structured = attribute(result, "structured_content", "structuredContent")
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


def server_environment(tmp_path: Path, compiler: Path) -> dict[str, str]:
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


async def call(
    session: ClientSession,
    trace: list[dict[str, Any]],
    name: str,
    arguments: dict[str, Any],
) -> Any:
    response = await session.call_tool(name, arguments=arguments)
    result = payload(response)
    trace.append({"tool": name, "arguments": arguments, "payload": result})
    assert attribute(response, "is_error", "isError") is not True, result
    assert result.get("ok") is True, result
    return result.get("result")


async def append_node(
    session: ClientSession,
    trace: list[dict[str, Any]],
    *,
    project: str,
    parent_id: str,
    node: NodeSpec,
) -> str:
    if isinstance(node, Atom):
        created = await call(
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

    created = await call(
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
        await append_node(
            session,
            trace,
            project=project,
            parent_id=node_id,
            node=child,
        )
    return node_id


def node_count(node: NodeSpec) -> int:
    if isinstance(node, Atom):
        return 1
    return 1 + sum(node_count(child) for child in node.children)


def run_checked(command: list[str]) -> subprocess.CompletedProcess[str]:
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


async def run_case(case: ProgramCase, tmp_path: Path, compiler: Path) -> dict[str, Any]:
    trace: list[dict[str, Any]] = []
    project = f"stress-{case.name}"
    structural_nodes = sum(node_count(node) for node in case.forms)
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "weave_jacquard.mcp_build"],
        env=server_environment(tmp_path, compiler),
        cwd=str(ROOT),
    )

    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        initialized = await session.initialize()
        server_info = attribute(initialized, "server_info", "serverInfo")
        assert server_info is not None
        assert server_info.name == "weave-mcp"

        await call(session, trace, "project_initialize", {"project": project})
        program = await call(
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
            await append_node(
                session,
                trace,
                project=project,
                parent_id=root_id,
                node=node,
            )

        rendered = await call(
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
        for token in case.source_tokens:
            assert token in source

        validated = await call(
            session,
            trace,
            "program_validate",
            {"project": project, "branch": "main", "document": DOCUMENT},
        )
        assert validated["available"] is True
        assert validated["valid"] is True
        assert str(validated["wir"]).strip()

        built = await call(
            session,
            trace,
            "program_build",
            {"project": project, "branch": "main", "document": DOCUMENT},
        )
        assert built["status"] == "succeeded"
        assert built["compiler_manifest_protocol_valid"] is True
        assert built["compiler_diagnostics_protocol_valid"] is True

        inspected = await call(
            session,
            trace,
            "build_get",
            {"build_id": built["build_id"]},
        )
        source_path = Path(inspected["artifact_paths"]["source"])
        executable = Path(inspected["artifact_paths"]["executable"])
        assert source_path.read_text(encoding="utf-8") == source + "\n"

        history = await call(
            session,
            trace,
            "branch_history",
            {
                "project": project,
                "branch": "main",
                "limit": structural_nodes + 10,
            },
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
    run_checked([str(compiler), "--frontend", str(wir_path), str(canonical_path)])
    run_checked([str(compiler), "--backend", str(wir_path), str(llvm_path)])
    llvm_as = shutil.which("llvm-as")
    assert llvm_as is not None
    run_checked([llvm_as, str(llvm_path), "-o", str(bitcode_path)])

    llvm = llvm_path.read_text(encoding="utf-8")
    assert "define i32 @main" in llvm
    for fragment in case.llvm_fragments:
        assert fragment in llvm

    summary = {
        "case": case.name,
        "expected_exit": case.expected_exit,
        "actual_exit": executed.returncode,
        "node_count": structural_nodes,
        "tool_calls": len(trace),
        "reachable_revisions": history["returned_count"],
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


def configured_compiler() -> Path:
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
    summary = asyncio.run(run_case(case, tmp_path, configured_compiler()))
    assert summary["actual_exit"] == case.expected_exit
    assert summary["node_count"] >= 20
    assert summary["tool_calls"] == summary["node_count"] + 7
    assert summary["reachable_revisions"] == summary["node_count"] + 2
