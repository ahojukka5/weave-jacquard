"""Bounded reads for compiler-generated text and JSON artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class CompilerFileTooLarge(ValueError):
    """Raised when a compiler-generated file exceeds its evidence ceiling."""

    def __init__(self, path: Path, *, limit: int, observed: int) -> None:
        super().__init__(
            f"compiler file {path.name!r} exceeds {limit} bytes "
            f"(observed at least {observed})"
        )
        self.path = path
        self.limit = limit
        self.observed = observed


def read_bounded_bytes(path: Path, *, max_bytes: int) -> bytes:
    """Read at most ``max_bytes`` and reject any additional byte."""

    if isinstance(max_bytes, bool) or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")
    with path.open("rb") as stream:
        payload = stream.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise CompilerFileTooLarge(
            path,
            limit=max_bytes,
            observed=len(payload),
        )
    return payload


def read_bounded_text(path: Path, *, max_bytes: int) -> str:
    """Read one bounded UTF-8 compiler text file."""

    return read_bounded_bytes(path, max_bytes=max_bytes).decode("utf-8")


def read_bounded_json(path: Path, *, max_bytes: int) -> Any:
    """Read and decode one bounded UTF-8 JSON file."""

    return json.loads(read_bounded_text(path, max_bytes=max_bytes))


__all__ = [
    "CompilerFileTooLarge",
    "read_bounded_bytes",
    "read_bounded_json",
    "read_bounded_text",
]
