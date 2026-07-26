from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tests.e2e.test_real_mcp_program_matrix import (
    NodeSpec,
    ProgramCase,
    add,
    configured_compiler,
    const_i32,
    const_i64,
    form,
    increment,
    local,
    param,
    run_case,
    sym,
)


def ptr_at(base: NodeSpec, index: NodeSpec) -> NodeSpec:
    return form(
        "ptr_add",
        base,
        form(
            "mul_i64",
            form("cast_i32_to_i64", index),
            const_i64(4),
        ),
    )


def store_item(index: int, value: int) -> NodeSpec:
    return form(
        "store_i32",
        form("call_ptr", sym("elem_ptr"), local("items"), const_i32(index)),
        const_i32(value),
    )


def binary_search_batch16() -> ProgramCase:
    stores = tuple(store_item(index, 2 * (index + 1)) for index in range(16))
    return ProgramCase(
        name="binary-search-batch16",
        expected_exit=26,
        forms=(
            form("entry", sym("main")),
            form(
                "fn",
                sym("elem_ptr"),
                form(
                    "params",
                    form("base", sym("ptr")),
                    form("index", sym("i32")),
                ),
                form("returns", sym("ptr")),
                form(
                    "do",
                    form("return", ptr_at(param("base"), param("index"))),
                ),
            ),
            form(
                "fn",
                sym("search16"),
                form(
                    "params",
                    form("items", sym("ptr")),
                    form("target", sym("i32")),
                ),
                form("returns", sym("i32")),
                form(
                    "do",
                    form("let", sym("low"), sym("i32"), const_i32(0)),
                    form("let", sym("high"), sym("i32"), const_i32(15)),
                    form("let", sym("found"), sym("i32"), const_i32(-1)),
                    form(
                        "while",
                        form(
                            "condition",
                            form(
                                "and_bool",
                                form("le_i32", local("low"), local("high")),
                                form("eq_i32", local("found"), const_i32(-1)),
                            ),
                        ),
                        form(
                            "do",
                            form(
                                "let",
                                sym("mid"),
                                sym("i32"),
                                form(
                                    "div_i32",
                                    add(local("low"), local("high")),
                                    const_i32(2),
                                ),
                            ),
                            form(
                                "let",
                                sym("mid_val"),
                                sym("i32"),
                                form(
                                    "load_i32",
                                    form(
                                        "call_ptr",
                                        sym("elem_ptr"),
                                        param("items"),
                                        local("mid"),
                                    ),
                                ),
                            ),
                            form(
                                "if",
                                form(
                                    "condition",
                                    form("eq_i32", local("mid_val"), param("target")),
                                ),
                                form(
                                    "then",
                                    form(
                                        "do",
                                        form("set", sym("found"), local("mid")),
                                    ),
                                ),
                                form(
                                    "else",
                                    form(
                                        "do",
                                        form(
                                            "if",
                                            form(
                                                "condition",
                                                form(
                                                    "lt_i32",
                                                    local("mid_val"),
                                                    param("target"),
                                                ),
                                            ),
                                            form(
                                                "then",
                                                form(
                                                    "do",
                                                    form(
                                                        "set",
                                                        sym("low"),
                                                        add(local("mid"), const_i32(1)),
                                                    ),
                                                ),
                                            ),
                                            form(
                                                "else",
                                                form(
                                                    "do",
                                                    form(
                                                        "set",
                                                        sym("high"),
                                                        form(
                                                            "sub_i32",
                                                            local("mid"),
                                                            const_i32(1),
                                                        ),
                                                    ),
                                                ),
                                            ),
                                        ),
                                    ),
                                ),
                            ),
                        ),
                    ),
                    form("return", local("found")),
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
                        sym("items"),
                        sym("ptr"),
                        form("call_ptr", sym("malloc"), const_i64(64)),
                    ),
                    form(
                        "if",
                        form(
                            "condition",
                            form("eq_ptr", local("items"), form("const_null")),
                        ),
                        form(
                            "then",
                            form("do", form("return", const_i32(-1))),
                        ),
                        form("else", form("do")),
                    ),
                    *stores,
                    form("let", sym("t"), sym("i32"), const_i32(0)),
                    form("let", sym("sum"), sym("i32"), const_i32(0)),
                    form(
                        "while",
                        form("condition", form("lt_i32", local("t"), const_i32(12))),
                        form(
                            "do",
                            form(
                                "let",
                                sym("target"),
                                sym("i32"),
                                add(
                                    form("mul_i32", local("t"), const_i32(3)),
                                    const_i32(7),
                                ),
                            ),
                            form(
                                "let",
                                sym("idx"),
                                sym("i32"),
                                form(
                                    "call_i32",
                                    sym("search16"),
                                    local("items"),
                                    local("target"),
                                ),
                            ),
                            form("set", sym("sum"), add(local("sum"), local("idx"))),
                            increment("t"),
                        ),
                    ),
                    form("call_void", sym("free"), local("items")),
                    form("return", local("sum")),
                ),
            ),
        ),
        source_tokens=("search16", "and_bool", "div_i32", "const_null"),
        llvm_fragments=(
            "define i32 @search16(ptr %items, i32 %target)",
            "sdiv i32",
            "call i32 @search16(ptr",
            "getelementptr i8",
            "phi i32",
        ),
    )


CASE = binary_search_batch16()


@pytest.mark.real_mcp
@pytest.mark.real_e2e
def test_real_mcp_binary_search_batch16(tmp_path: Path) -> None:
    summary = asyncio.run(run_case(CASE, tmp_path, configured_compiler()))
    assert summary["actual_exit"] == 26
    assert summary["node_count"] > 250
    assert summary["tool_calls"] == summary["node_count"] + 7
    assert summary["reachable_revisions"] == summary["node_count"] + 2
