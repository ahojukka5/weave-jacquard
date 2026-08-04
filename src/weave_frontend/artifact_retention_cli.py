"""Operator CLI for deterministic retained-artifact dry-run planning."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, BinaryIO

from .artifact_retention import ArtifactRetentionPlanner
from .errors import ValidationError, WeaveFrontendError
from .mcp_artifact_storage import artifact_reconciliation
from .runtime_container import close_runtime_services

MAX_RETENTION_POLICY_BYTES = 1_048_576


def build_parser() -> argparse.ArgumentParser:
    """Build the operator-only retention planning parser."""

    parser = argparse.ArgumentParser(
        prog="weave-artifact-retention-plan",
        description=(
            "Create a read-only retention plan from an exact reconciliation ID. "
            "This command never quarantines or deletes artifacts."
        ),
    )
    parser.add_argument(
        "--policy",
        required=True,
        help="retention policy JSON path, or '-' for standard input",
    )
    parser.add_argument(
        "--as-of-unix-ns",
        required=True,
        type=int,
        help="explicit non-negative Unix timestamp in nanoseconds",
    )
    return parser


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


def generate_plan(
    policy: Mapping[str, Any],
    *,
    as_of_unix_ns: int,
) -> dict[str, Any]:
    """Create one plan through the production reconciliation service."""

    return ArtifactRetentionPlanner(artifact_reconciliation()).plan(
        policy,
        as_of_unix_ns=as_of_unix_ns,
    )


def _error_payload(exc: WeaveFrontendError) -> dict[str, Any]:
    if isinstance(exc, ValidationError):
        error = exc.as_dict()
    else:
        error = {
            "code": type(exc).__name__,
            "message": str(exc),
        }
    return {"ok": False, "error": error}


def main() -> None:
    """Print one deterministic dry-run plan or one structured domain error."""

    args = build_parser().parse_args()
    try:
        policy = load_policy(args.policy)
        plan = generate_plan(policy, as_of_unix_ns=args.as_of_unix_ns)
    except WeaveFrontendError as exc:
        print(
            json.dumps(_error_payload(exc), indent=2, sort_keys=True),
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    finally:
        close_runtime_services()
    print(json.dumps(plan, indent=2, sort_keys=True))


__all__ = [
    "MAX_RETENTION_POLICY_BYTES",
    "build_parser",
    "generate_plan",
    "load_policy",
    "main",
]


if __name__ == "__main__":
    main()
