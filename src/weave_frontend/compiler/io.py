"""Bounded reads for compiler-generated text and JSON artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..retained_artifact_io import (
    RetainedArtifactReadError,
    RetainedArtifactTooLarge,
    read_bounded_regular_bytes,
    read_bounded_regular_json,
)


class CompilerFileTooLarge(ValueError):
    """Raised when a compiler-generated file exceeds its evidence ceiling."""

    def __init__(self, path: Path, *, limit: int, observed: int) -> None:
        super().__init__(
            f"compiler file {path.name!r} exceeds {limit} bytes (observed at least {observed})"
        )
        self.path = path
        self.limit = limit
        self.observed = observed


def read_bounded_bytes(path: Path, *, max_bytes: int) -> bytes:
    """Read at most ``max_bytes`` and reject any additional byte."""

    try:
        return read_bounded_regular_bytes(path, max_bytes=max_bytes)
    except RetainedArtifactTooLarge as exc:
        raise CompilerFileTooLarge(path, limit=exc.limit, observed=exc.observed) from exc
    except RetainedArtifactReadError as exc:
        raise OSError("cannot read regular compiler file") from exc


def read_bounded_text(path: Path, *, max_bytes: int) -> str:
    """Read one bounded UTF-8 compiler text file."""

    return read_bounded_bytes(path, max_bytes=max_bytes).decode("utf-8")


def read_bounded_json(path: Path, *, max_bytes: int) -> Any:
    """Read and decode one bounded UTF-8 JSON file."""

    try:
        return read_bounded_regular_json(path, max_bytes=max_bytes)
    except RetainedArtifactTooLarge as exc:
        raise CompilerFileTooLarge(path, limit=exc.limit, observed=exc.observed) from exc
    except RetainedArtifactReadError as exc:
        raise OSError("cannot decode regular compiler JSON file") from exc


__all__ = [
    "CompilerFileTooLarge",
    "read_bounded_bytes",
    "read_bounded_json",
    "read_bounded_text",
]
