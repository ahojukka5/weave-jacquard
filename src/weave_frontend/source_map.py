"""Deterministic canonical Weave rendering with stable node source spans."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .errors import ValidationError
from .sexpr import JsonObject, validate_tree
from .structural_limits import MAX_RENDERED_SOURCE_BYTES


@dataclass(frozen=True)
class SourcePosition:
    byte: int
    line: int
    column: int


class _Writer:
    def __init__(self) -> None:
        self.parts: list[str] = []
        self.byte = 0
        self.line = 1
        self.column = 1
        self.spans: dict[str, dict[str, int | str]] = {}

    def position(self) -> SourcePosition:
        return SourcePosition(self.byte, self.line, self.column)

    def append(self, text: str) -> None:
        encoded_bytes = len(text.encode("utf-8"))
        next_byte = self.byte + encoded_bytes
        if next_byte > MAX_RENDERED_SOURCE_BYTES:
            raise ValidationError(
                "RENDERED_SOURCE_TOO_LARGE",
                f"rendered source exceeds {MAX_RENDERED_SOURCE_BYTES} UTF-8 bytes",
            )
        self.parts.append(text)
        self.byte = next_byte
        if "\n" in text:
            lines = text.split("\n")
            self.line += len(lines) - 1
            self.column = len(lines[-1]) + 1
        else:
            self.column += len(text)

    def record(self, node_id: str, start: SourcePosition) -> None:
        end = self.position()
        self.spans[node_id] = {
            "node_id": node_id,
            "start_byte": start.byte,
            "end_byte": end.byte,
            "start_line": start.line,
            "start_column": start.column,
            "end_line": end.line,
            "end_column": end.column,
        }

    def text(self) -> str:
        return "".join(self.parts)


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


def _flat_width_if_fits(node: JsonObject, remaining: int) -> int | None:
    """Return flat character width, stopping as soon as the line cannot fit."""

    if remaining < 0:
        return None
    if node["kind"] != "list":
        width = len(_render_atom(node))
        return width if width <= remaining else None

    used = 1  # opening parenthesis
    for index, child in enumerate(node["children"]):
        if index:
            if used + 1 > remaining:
                return None
            used += 1
        child_width = _flat_width_if_fits(child, remaining - used)
        if child_width is None:
            return None
        used += child_width
    if used + 1 > remaining:
        return None
    return used + 1  # closing parenthesis


def _render(node: JsonObject, writer: _Writer, *, indent: int) -> None:
    start = writer.position()
    if node["kind"] != "list":
        writer.append(_render_atom(node))
        writer.record(node["id"], start)
        return

    children = node["children"]
    if not children:
        writer.append("()")
        writer.record(node["id"], start)
        return

    if _flat_width_if_fits(node, max(0, 88 - indent)) is not None:
        writer.append("(")
        for index, child in enumerate(children):
            if index:
                writer.append(" ")
            _render(child, writer, indent=indent + 2)
        writer.append(")")
        writer.record(node["id"], start)
        return

    writer.append("(")
    _render(children[0], writer, indent=indent + 2)
    padding = " " * (indent + 2)
    for child in children[1:]:
        writer.append("\n" + padding)
        _render(child, writer, indent=indent + 2)
    writer.append(")")
    writer.record(node["id"], start)


def render_with_node_map(
    root: JsonObject,
    *,
    revision_id: str,
    document: str,
) -> tuple[str, dict[str, Any]]:
    """Render compiler source and a sidecar mapping source spans to node IDs."""

    validate_tree(root)
    writer = _Writer()
    _render(root, writer, indent=0)
    writer.append("\n")
    source = writer.text()
    source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    node_map: dict[str, Any] = {
        "format": "weave-node-map-v1",
        "source_sha256": source_hash,
        "revision_id": revision_id,
        "document": document,
        "nodes": sorted(
            writer.spans.values(),
            key=lambda span: (int(span["start_byte"]), -int(span["end_byte"])),
        ),
    }
    return source, node_map


def smallest_node_for_span(
    node_map: dict[str, Any],
    *,
    start_byte: int,
    end_byte: int,
) -> str | None:
    """Return the smallest mapped node containing an exclusive-end span."""

    matches = [
        span
        for span in node_map.get("nodes", [])
        if int(span["start_byte"]) <= start_byte and int(span["end_byte"]) >= end_byte
    ]
    if not matches:
        return None
    match = min(
        matches,
        key=lambda span: (
            int(span["end_byte"]) - int(span["start_byte"]),
            -int(span["start_byte"]),
        ),
    )
    return str(match["node_id"])
