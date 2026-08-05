"""Bounded race-resistant reads for immutable retained artifact metadata."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any


class RetainedArtifactReadError(ValueError):
    """Raised when retained metadata cannot be read as a safe regular file."""


class RetainedArtifactTooLarge(RetainedArtifactReadError):
    """Raised when retained metadata exceeds its declared byte ceiling."""

    def __init__(self, path: Path, *, limit: int, observed: int) -> None:
        super().__init__(
            f"retained artifact {path.name!r} exceeds {limit} bytes (observed at least {observed})"
        )
        self.path = path
        self.limit = limit
        self.observed = observed


def read_bounded_regular_bytes(path: Path, *, max_bytes: int) -> bytes:
    """Read one non-symlink regular file without consuming more than its limit."""

    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")

    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    try:
        before = path.lstat()
    except OSError as exc:
        raise RetainedArtifactReadError(f"cannot inspect retained artifact: {exc}") from exc
    if stat.S_ISLNK(before.st_mode):
        raise RetainedArtifactReadError("retained artifact must not be a symlink")

    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RetainedArtifactReadError(f"cannot open retained artifact: {exc}") from exc

    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise RetainedArtifactReadError("retained artifact must be a regular file")
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise RetainedArtifactReadError("retained artifact changed while opening")
        if opened.st_size > max_bytes:
            raise RetainedArtifactTooLarge(
                path,
                limit=max_bytes,
                observed=opened.st_size,
            )

        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            payload = stream.read(max_bytes + 1)
        if len(payload) > max_bytes:
            raise RetainedArtifactTooLarge(
                path,
                limit=max_bytes,
                observed=len(payload),
            )
        return payload
    finally:
        os.close(descriptor)


def read_bounded_regular_json(path: Path, *, max_bytes: int) -> Any:
    """Read and decode one bounded non-symlink UTF-8 JSON artifact."""

    payload = read_bounded_regular_bytes(path, max_bytes=max_bytes)
    try:
        text = payload.decode("utf-8")
        return json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RetainedArtifactReadError(f"invalid retained artifact JSON: {exc}") from exc


__all__ = [
    "RetainedArtifactReadError",
    "RetainedArtifactTooLarge",
    "read_bounded_regular_bytes",
    "read_bounded_regular_json",
]
