"""Minimal, deterministic grammar and semantic checker for prototype Weave ASTs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any
from uuid import uuid4

from .errors import ValidationError

Json = dict[str, Any]
NUMERIC_TYPES = {"i32", "i64"}
SCALAR_TYPES = NUMERIC_TYPES | {"bool", "void"}
STATEMENTS = {"hole", "let", "set", "if", "while", "return", "expr"}
EXPRESSIONS = {"const", "param", "local", "call", "binary"}
BINARY_NUMERIC = {"add", "sub", "mul", "div", "mod"}
BINARY_COMPARE = {"eq", "ne", "lt", "le", "gt", "ge"}
BINARY_LOGICAL = {"and", "or"}


def ensure_node_ids(value: Any, created: list[str] | None = None) -> Any:
    """Recursively add stable IDs to AST nodes while preserving user payloads."""
    created = created if created is not None else []
    if isinstance(value, list):
        return [ensure_node_ids(item, created) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: ensure_node_ids(item, created) for key, item in value.items()}
    if "kind" in result and "id" not in result:
        node_id = str(uuid4())
        result["id"] = node_id
        created.append(node_id)
    return result


def walk_nodes(value: Any) -> Iterable[Json]:
    if isinstance(value, dict):
        if "kind" in value:
            yield value
        for child in value.values():
            yield from walk_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_nodes(child)


def find_node(value: Any, node_id: str) -> Json | None:
    return next((node for node in walk_nodes(value) if node.get("id") == node_id), None)


def contains_holes(value: Any) -> bool:
    return any(node.get("kind") == "hole" for node in walk_nodes(value))


def validate_function_shape(function: Json) -> None:
    required = {"kind", "name", "params", "returns", "body"}
    missing = required - function.keys()
    if missing:
        raise ValidationError("MISSING_FIELD", f"function missing fields: {sorted(missing)}")
    if function["kind"] != "fn":
        raise ValidationError("INVALID_KIND", "top-level symbol must have kind 'fn'")
    if not isinstance(function["name"], str) or not function["name"]:
        raise ValidationError("INVALID_NAME", "function name must be a non-empty string")
    if function["returns"] not in SCALAR_TYPES:
        raise ValidationError("UNKNOWN_TYPE", f"unsupported return type {function['returns']!r}")
    if not isinstance(function["params"], list) or not isinstance(function["body"], list):
        raise ValidationError("INVALID_SHAPE", "params and body must be arrays")
    names: set[str] = set()
    for param in function["params"]:
        if not isinstance(param, dict) or set(param) < {"name", "type"}:
            raise ValidationError("INVALID_PARAM", "parameters require name and type")
        if param["name"] in names:
            raise ValidationError("DUPLICATE_PARAM", f"duplicate parameter {param['name']}")
        if param["type"] not in SCALAR_TYPES - {"void"}:
            raise ValidationError("UNKNOWN_TYPE", f"unsupported parameter type {param['type']!r}")
        names.add(param["name"])
    for statement in function["body"]:
        validate_statement_shape(statement)


def validate_statement_shape(statement: Any) -> None:
    if not isinstance(statement, dict):
        raise ValidationError("INVALID_STATEMENT", "statement must be an object")
    kind = statement.get("kind")
    if kind not in STATEMENTS:
        raise ValidationError("INVALID_STATEMENT_KIND", f"unsupported statement kind {kind!r}")
    if kind == "hole":
        if statement.get("category", "statement") != "statement":
            raise ValidationError(
                "INVALID_HOLE",
                "statement hole must declare category='statement'",
            )
        return
    if kind == "let":
        _require(statement, "name", "type", "value")
        if statement["type"] not in SCALAR_TYPES - {"void"}:
            raise ValidationError("UNKNOWN_TYPE", f"unsupported local type {statement['type']!r}")
        validate_expression_shape(statement["value"])
    elif kind == "set":
        _require(statement, "name", "value")
        validate_expression_shape(statement["value"])
    elif kind in {"if", "while"}:
        _require(statement, "condition")
        validate_expression_shape(statement["condition"])
        body_keys = ("then", "else") if kind == "if" else ("body",)
        for key in body_keys:
            body = statement.get(key, [])
            if not isinstance(body, list):
                raise ValidationError("INVALID_BLOCK", f"{kind}.{key} must be an array")
            for child in body:
                validate_statement_shape(child)
    elif kind == "return":
        if "value" in statement and statement["value"] is not None:
            validate_expression_shape(statement["value"])
    elif kind == "expr":
        _require(statement, "value")
        validate_expression_shape(statement["value"])


def validate_expression_shape(expression: Any) -> None:
    if not isinstance(expression, dict):
        raise ValidationError("INVALID_EXPRESSION", "expression must be an object")
    kind = expression.get("kind")
    if kind not in EXPRESSIONS:
        raise ValidationError("INVALID_EXPRESSION_KIND", f"unsupported expression kind {kind!r}")
    if kind == "const":
        _require(expression, "type", "value")
        if expression["type"] not in SCALAR_TYPES - {"void"}:
            raise ValidationError(
                "UNKNOWN_TYPE",
                f"unsupported constant type {expression['type']!r}",
            )
    elif kind in {"param", "local"}:
        _require(expression, "name")
    elif kind == "call":
        _require(expression, "function", "args")
        if not isinstance(expression["args"], list):
            raise ValidationError("INVALID_CALL", "call.args must be an array")
        for arg in expression["args"]:
            validate_expression_shape(arg)
    elif kind == "binary":
        _require(expression, "op", "left", "right")
        if expression["op"] not in BINARY_NUMERIC | BINARY_COMPARE | BINARY_LOGICAL:
            raise ValidationError(
                "UNKNOWN_OPERATOR",
                f"unsupported binary operator {expression['op']!r}",
            )
        validate_expression_shape(expression["left"])
        validate_expression_shape(expression["right"])


def validate_function_semantics(function: Json, interfaces: Mapping[str, Json]) -> None:
    validate_function_shape(function)
    if contains_holes(function):
        raise ValidationError("UNRESOLVED_HOLE", "function contains unresolved syntax holes")
    params = {item["name"]: item["type"] for item in function["params"]}
    _validate_block(function["body"], params, {}, function["returns"], interfaces)


def _validate_block(
    body: list[Json],
    params: Mapping[str, str],
    inherited_locals: Mapping[str, str],
    return_type: str,
    interfaces: Mapping[str, Json],
) -> None:
    locals_: dict[str, str] = dict(inherited_locals)
    for statement in body:
        kind = statement["kind"]
        node_id = statement.get("id")
        if kind == "let":
            name = statement["name"]
            if name in params or name in locals_:
                raise ValidationError("DUPLICATE_LOCAL", f"duplicate local {name}", node_id=node_id)
            actual = _expression_type(statement["value"], params, locals_, interfaces)
            _expect(statement["type"], actual, node_id)
            locals_[name] = statement["type"]
        elif kind == "set":
            name = statement["name"]
            if name not in locals_:
                raise ValidationError("UNKNOWN_LOCAL", f"unknown local {name}", node_id=node_id)
            actual = _expression_type(statement["value"], params, locals_, interfaces)
            _expect(locals_[name], actual, node_id)
        elif kind == "if":
            condition_type = _expression_type(
                statement["condition"], params, locals_, interfaces
            )
            _expect("bool", condition_type, node_id)
            _validate_block(statement.get("then", []), params, locals_, return_type, interfaces)
            _validate_block(statement.get("else", []), params, locals_, return_type, interfaces)
        elif kind == "while":
            condition_type = _expression_type(
                statement["condition"], params, locals_, interfaces
            )
            _expect("bool", condition_type, node_id)
            _validate_block(statement.get("body", []), params, locals_, return_type, interfaces)
        elif kind == "return":
            actual = "void" if statement.get("value") is None else _expression_type(
                statement["value"], params, locals_, interfaces
            )
            _expect(return_type, actual, node_id)
        elif kind == "expr":
            _expression_type(statement["value"], params, locals_, interfaces)


def _expression_type(
    expression: Json,
    params: Mapping[str, str],
    locals_: Mapping[str, str],
    interfaces: Mapping[str, Json],
) -> str:
    kind = expression["kind"]
    node_id = expression.get("id")
    if kind == "const":
        return expression["type"]
    if kind == "param":
        try:
            return params[expression["name"]]
        except KeyError as exc:
            raise ValidationError(
                "UNKNOWN_PARAM", f"unknown parameter {expression['name']}", node_id=node_id
            ) from exc
    if kind == "local":
        try:
            return locals_[expression["name"]]
        except KeyError as exc:
            raise ValidationError(
                "UNKNOWN_LOCAL", f"unknown local {expression['name']}", node_id=node_id
            ) from exc
    if kind == "call":
        name = expression["function"]
        matches = [
            interface
            for key, interface in interfaces.items()
            if key == name or key.endswith(f".{name}")
        ]
        if len(matches) != 1:
            code = "UNKNOWN_FUNCTION" if not matches else "AMBIGUOUS_FUNCTION"
            raise ValidationError(code, f"cannot resolve function {name!r}", node_id=node_id)
        interface = matches[0]
        args = expression["args"]
        expected_params = interface["params"]
        if len(args) != len(expected_params):
            raise ValidationError(
                "WRONG_ARITY",
                f"{name} expects {len(expected_params)} arguments, got {len(args)}",
                node_id=node_id,
            )
        for arg, expected in zip(args, expected_params, strict=True):
            _expect(expected["type"], _expression_type(arg, params, locals_, interfaces), node_id)
        return interface["returns"]
    if kind == "binary":
        left = _expression_type(expression["left"], params, locals_, interfaces)
        right = _expression_type(expression["right"], params, locals_, interfaces)
        _expect(left, right, node_id)
        op = expression["op"]
        if op in BINARY_NUMERIC:
            if left not in NUMERIC_TYPES:
                raise ValidationError(
                    "TYPE_MISMATCH",
                    f"{op} requires numeric operands",
                    node_id=node_id,
                )
            return left
        if op in BINARY_COMPARE:
            return "bool"
        if left != "bool":
            raise ValidationError("TYPE_MISMATCH", f"{op} requires bool operands", node_id=node_id)
        return "bool"
    raise AssertionError(f"unhandled expression kind: {kind}")


def _expect(expected: str, actual: str, node_id: str | None) -> None:
    if expected != actual:
        raise ValidationError(
            "TYPE_MISMATCH", f"expected {expected}, got {actual}", node_id=node_id
        )


def _require(value: Mapping[str, Any], *keys: str) -> None:
    missing = [key for key in keys if key not in value]
    if missing:
        raise ValidationError("MISSING_FIELD", f"node missing fields: {missing}")
