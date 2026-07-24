"""Deterministic rendering of the prototype AST to canonical surface Weave."""

from __future__ import annotations

from typing import Any

Json = dict[str, Any]


def render_module(module: Json) -> str:
    lines = ["(program", f'  (name "{module["name"]}")', '  (version "0.1")']
    for imported in sorted(module.get("imports", [])):
        lines.append(f"  (import {imported})")
    for function in sorted(module.get("functions", []), key=lambda item: item["name"]):
        lines.append("")
        lines.extend(_render_function(function, 1))
    lines.append(")")
    return "\n".join(lines) + "\n"


def _render_function(function: Json, depth: int) -> list[str]:
    pad = "  " * depth
    params = " ".join(
        f'({item["name"]} {item["type"]})' for item in function["params"]
    )
    params_form = f"(params {params})" if params else "(params)"
    lines = [f"{pad}(fn {function['name']}", f"{pad}  {params_form}"]
    lines.append(f"{pad}  (returns {function['returns']})")
    lines.append(f"{pad}  (do")
    for statement in function["body"]:
        lines.extend(_render_statement(statement, depth + 2))
    lines[-1] = lines[-1] + "))" if function["body"] else f"{pad}  (do))"
    return lines


def _render_statement(statement: Json, depth: int) -> list[str]:
    pad = "  " * depth
    kind = statement["kind"]
    if kind == "hole":
        return [f"{pad}(hole statement)"]
    if kind == "let":
        return [
            f"{pad}(let {statement['name']} {statement['type']} "
            f"{_render_expr(statement['value'])})"
        ]
    if kind == "set":
        return [f"{pad}(set {statement['name']} {_render_expr(statement['value'])})"]
    if kind == "return":
        value = statement.get("value")
        return [f"{pad}(return{'' if value is None else ' ' + _render_expr(value)})"]
    if kind == "expr":
        return [f"{pad}{_render_expr(statement['value'])}"]
    if kind == "if":
        lines = [
            f"{pad}(if",
            f"{pad}  (condition {_render_expr(statement['condition'])})",
            f"{pad}  (then (do",
        ]
        for child in statement.get("then", []):
            lines.extend(_render_statement(child, depth + 3))
        lines.append(f"{pad}  ))")
        lines.append(f"{pad}  (else (do")
        for child in statement.get("else", []):
            lines.extend(_render_statement(child, depth + 3))
        lines.append(f"{pad}  )))")
        return lines
    if kind == "while":
        lines = [
            f"{pad}(while",
            f"{pad}  (condition {_render_expr(statement['condition'])})",
            f"{pad}  (do",
        ]
        for child in statement.get("body", []):
            lines.extend(_render_statement(child, depth + 2))
        lines.append(f"{pad}  ))")
        return lines
    raise AssertionError(kind)


def _render_expr(expression: Json) -> str:
    kind = expression["kind"]
    if kind == "const":
        value = (
            str(expression["value"]).lower()
            if isinstance(expression["value"], bool)
            else expression["value"]
        )
        return f"(const_{expression['type']} {value})"
    if kind == "param":
        return f"(param_get {expression['name']})"
    if kind == "local":
        return f"(local_get {expression['name']})"
    if kind == "call":
        args = " ".join(_render_expr(arg) for arg in expression["args"])
        return f"(call {expression['function']}{' ' if args else ''}{args})"
    if kind == "binary":
        return (
            f"({expression['op']} {_render_expr(expression['left'])} "
            f"{_render_expr(expression['right'])})"
        )
    raise AssertionError(kind)
