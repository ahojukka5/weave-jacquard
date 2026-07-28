"""Generic, grammar-neutral S-expression tree primitives."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Iterator
from typing import Any
from uuid import uuid4

from .errors import NotFoundError, ValidationError

JsonObject = dict[str, Any]
ATOM_KINDS = {"symbol", "string", "integer", "float", "boolean"}
NODE_ID_PATTERN = re.compile(r"^n_[A-Za-z0-9_-]+$")


def new_node_id() -> str:
    """Return a compact, globally improbable node identity."""

    return f"n_{uuid4().hex[:16]}"


def make_atom(kind: str, value: Any, *, node_id: str | None = None) -> JsonObject:
    node = {"id": node_id or new_node_id(), "kind": kind, "value": value}
    validate_node(node)
    return node


def make_list(
    children: list[JsonObject] | None = None,
    *,
    node_id: str | None = None,
) -> JsonObject:
    node = {"id": node_id or new_node_id(), "kind": "list", "children": children or []}
    validate_tree(node)
    return node


def make_form(head: str, *, node_id: str | None = None) -> JsonObject:
    return make_list([make_atom("symbol", head)], node_id=node_id)


def validate_node(node: Any) -> None:
    if not isinstance(node, dict):
        raise ValidationError("INVALID_NODE", "node must be an object")
    node_id = node.get("id")
    if not isinstance(node_id, str) or not NODE_ID_PATTERN.match(node_id):
        raise ValidationError("INVALID_NODE_ID", "node id must start with 'n_'", node_id=node_id)
    kind = node.get("kind")
    if kind == "list":
        children = node.get("children")
        if not isinstance(children, list):
            raise ValidationError(
                "INVALID_LIST",
                "list node requires a children array",
                node_id=node_id,
            )
        return
    if kind not in ATOM_KINDS:
        raise ValidationError(
            "INVALID_NODE_KIND",
            f"unsupported node kind {kind!r}",
            node_id=node_id,
        )
    if "value" not in node:
        raise ValidationError("MISSING_VALUE", "atom node requires a value", node_id=node_id)
    value = node["value"]
    if kind in {"symbol", "string"} and not isinstance(value, str):
        raise ValidationError("INVALID_VALUE", f"{kind} value must be a string", node_id=node_id)
    if kind == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
        raise ValidationError("INVALID_VALUE", "integer value must be an integer", node_id=node_id)
    if kind == "float" and (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValidationError(
            "INVALID_VALUE",
            "float value must be a finite number other than boolean",
            node_id=node_id,
        )
    if kind == "boolean" and not isinstance(value, bool):
        raise ValidationError(
            "INVALID_VALUE",
            "boolean value must be true or false",
            node_id=node_id,
        )


def validate_tree(root: JsonObject) -> None:
    seen: set[str] = set()
    for node in walk_nodes(root):
        validate_node(node)
        node_id = node["id"]
        if node_id in seen:
            raise ValidationError(
                "DUPLICATE_NODE_ID",
                f"duplicate node id {node_id}",
                node_id=node_id,
            )
        seen.add(node_id)


def walk_nodes(root: Any) -> Iterable[JsonObject]:
    if not isinstance(root, dict):
        return
    yield root
    if root.get("kind") == "list":
        for child in root.get("children", []):
            yield from walk_nodes(child)


def find_node(root: JsonObject, node_id: str) -> JsonObject:
    for node in walk_nodes(root):
        if node.get("id") == node_id:
            return node
    raise NotFoundError(f"node {node_id!r} not found")


def find_parent(root: JsonObject, node_id: str) -> tuple[JsonObject, int]:
    for node in walk_nodes(root):
        if node.get("kind") != "list":
            continue
        for index, child in enumerate(node["children"]):
            if child.get("id") == node_id:
                return node, index
    raise NotFoundError(f"node {node_id!r} has no parent")


def head_symbol(node: JsonObject) -> str | None:
    if node.get("kind") != "list" or not node.get("children"):
        return None
    head = node["children"][0]
    if head.get("kind") != "symbol":
        return None
    return str(head["value"])


def render_node(
    node: JsonObject,
    *,
    annotated: bool = False,
    annotate_atoms: bool = False,
    indent: int = 0,
) -> str:
    """Render canonical source or an ID-bearing agent view."""

    validate_tree(node)
    if annotated:
        return _render_annotated(
            node,
            indent=indent,
            annotate_atoms=annotate_atoms,
        )
    parts: list[str] = []
    _render_canonical(node, parts, indent=indent)
    return "".join(parts)


def _render_canonical(node: JsonObject, parts: list[str], *, indent: int) -> None:
    if node["kind"] != "list":
        parts.append(_render_atom(node))
        return

    children = node["children"]
    if not children:
        parts.append("()")
        return

    flat = _flat_text_if_fits(node, max(0, 88 - indent))
    if flat is not None:
        parts.append(flat)
        return

    parts.append("(")
    _render_canonical(children[0], parts, indent=indent + 2)
    padding = " " * (indent + 2)
    for child in children[1:]:
        parts.append("\n" + padding)
        _render_canonical(child, parts, indent=indent + 2)
    parts.append(")")


def _flat_text_if_fits(node: JsonObject, remaining: int) -> str | None:
    if remaining < 0:
        return None
    if node["kind"] != "list":
        text = _render_atom(node)
        return text if len(text) <= remaining else None

    parts = ["("]
    used = 1
    for index, child in enumerate(node["children"]):
        if index:
            if used + 1 > remaining:
                return None
            parts.append(" ")
            used += 1
        child_text = _flat_text_if_fits(child, remaining - used)
        if child_text is None:
            return None
        parts.append(child_text)
        used += len(child_text)
    if used + 1 > remaining:
        return None
    parts.append(")")
    return "".join(parts)


def _render_annotated(node: JsonObject, *, indent: int, annotate_atoms: bool) -> str:
    if node["kind"] != "list":
        text = _render_atom(node)
        if annotate_atoms:
            return f"(@{node['id']} {text})"
        return text

    children = node["children"]
    if not children:
        core = "()"
    else:
        child_text = [
            _render_annotated(
                child,
                indent=indent + 2,
                annotate_atoms=annotate_atoms,
            )
            for child in children
        ]
        compact = "(" + " ".join(child_text) + ")"
        if all("\n" not in text for text in child_text) and indent + len(compact) <= 88:
            core = compact
        else:
            head = child_text[0]
            rest = child_text[1:]
            if not rest:
                core = f"({head})"
            else:
                pad = " " * (indent + 2)
                aligned = [(pad + text.replace("\n", "\n" + pad)) for text in rest]
                core = f"({head}\n" + "\n".join(aligned) + ")"
    wrapper_pad = " " * (indent + 2)
    wrapped = core.replace("\n", "\n" + wrapper_pad)
    return f"(@{node['id']} {wrapped})"


def _render_atom(node: JsonObject) -> str:
    kind = node["kind"]
    value = node["value"]
    if kind == "string":
        escaped = (
            value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )
        return f'"{escaped}"'
    if kind == "boolean":
        return "true" if value else "false"
    if kind == "float":
        return repr(float(value))
    return str(value)


class _Token:
    def __init__(self, kind: str, value: str, position: int) -> None:
        self.kind = kind
        self.value = value
        self.position = position


def parse_source(source: str) -> JsonObject:
    """Parse one generic S-expression, including the agent @node wrapper."""

    tokens = iter(_tokenize(source))
    buffered: list[_Token] = []

    def next_token() -> _Token | None:
        if buffered:
            return buffered.pop()
        return next(tokens, None)

    def push(token: _Token) -> None:
        buffered.append(token)

    def parse_one() -> JsonObject:
        token = next_token()
        if token is None:
            raise ValidationError("UNEXPECTED_EOF", "expected an S-expression")
        if token.kind == "LPAREN":
            children: list[JsonObject] = []
            while True:
                item = next_token()
                if item is None:
                    raise ValidationError("UNEXPECTED_EOF", "unterminated list")
                if item.kind == "RPAREN":
                    break
                push(item)
                children.append(parse_one())
            node = make_list(children)
            if (
                len(children) == 2
                and children[0].get("kind") == "symbol"
                and str(children[0].get("value", "")).startswith("@n_")
            ):
                wrapped = children[1]
                wrapped["id"] = str(children[0]["value"])[1:]
                validate_tree(wrapped)
                return wrapped
            return node
        if token.kind == "RPAREN":
            raise ValidationError("UNEXPECTED_RPAREN", "unexpected ')' in source")
        if token.kind == "STRING":
            return make_atom("string", token.value)
        return _parse_atom(token.value)

    root = parse_one()
    trailing = next_token()
    if trailing is not None:
        raise ValidationError("TRAILING_INPUT", "source contains more than one top-level form")
    validate_tree(root)
    return root


def _parse_atom(value: str) -> JsonObject:
    if value == "true":
        return make_atom("boolean", True)
    if value == "false":
        return make_atom("boolean", False)
    if re.fullmatch(r"[-+]?\d+", value):
        return make_atom("integer", int(value))
    if re.fullmatch(
        r"[-+]?(?:(?:\d+\.\d*|\d*\.\d+)(?:[eE][-+]?\d+)?|\d+[eE][-+]?\d+)",
        value,
    ):
        return make_atom("float", float(value))
    return make_atom("symbol", value)


def _tokenize(source: str) -> Iterator[_Token]:
    index = 0
    length = len(source)
    while index < length:
        char = source[index]
        if char.isspace():
            index += 1
            continue
        if char == ";":
            while index < length and source[index] not in "\r\n":
                index += 1
            continue
        if char == "(":
            yield _Token("LPAREN", char, index)
            index += 1
            continue
        if char == ")":
            yield _Token("RPAREN", char, index)
            index += 1
            continue
        if char == '"':
            start = index
            index += 1
            value: list[str] = []
            while index < length:
                char = source[index]
                if char == '"':
                    index += 1
                    yield _Token("STRING", "".join(value), start)
                    break
                if char == "\\":
                    index += 1
                    if index >= length:
                        raise ValidationError("INVALID_STRING", "unterminated string escape")
                    escaped = source[index]
                    mapping = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}
                    value.append(mapping.get(escaped, "\\" + escaped))
                    index += 1
                    continue
                value.append(char)
                index += 1
                continue
            else:
                raise ValidationError("INVALID_STRING", "unterminated string literal")
            continue
        start = index
        while index < length and not source[index].isspace() and source[index] not in "();":
            index += 1
        if start == index:
            raise ValidationError("INVALID_TOKEN", f"invalid token at offset {index}")
        yield _Token("ATOM", source[start:index], start)
