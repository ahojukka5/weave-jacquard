"""Bounded operator input for retained-artifact policies."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, BinaryIO

from ...errors import ValidationError

MAX_RETENTION_POLICY_BYTES = 1_048_576


def _read_bounded(stream: BinaryIO) -> bytes:
    payload = stream.read(MAX_RETENTION_POLICY_BYTES + 1)
    if len(payload) > MAX_RETENTION_POLICY_BYTES:
        raise ValidationError(
            "ARTIFACT_RETENTION_POLICY_TOO_LARGE",
            "retention policy exceeds the bounded input size",
        )
    return payload


def load_policy(value: str) -> Mapping[str, Any]:
    """Read one bounded UTF-8 JSON policy from a path or standard input."""

    try:
        if value == "-":
            payload = _read_bounded(sys.stdin.buffer)
        else:
            with Path(value).open("rb") as stream:
                payload = _read_bounded(stream)
    except OSError as exc:
        raise ValidationError(
            "ARTIFACT_RETENTION_POLICY_UNAVAILABLE",
            "cannot read the retention policy",
        ) from exc
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(
            "ARTIFACT_RETENTION_POLICY_INVALID",
            "retention policy must be valid UTF-8 JSON",
        ) from exc
    if not isinstance(decoded, Mapping):
        raise ValidationError(
            "ARTIFACT_RETENTION_POLICY_INVALID",
            "retention policy must be a JSON object",
        )
    return decoded


__all__ = [
    "MAX_RETENTION_POLICY_BYTES",
    "load_policy",
]
