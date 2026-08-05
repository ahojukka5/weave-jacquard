"""Operator CLI for guarded retained-artifact quarantine publication."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, BinaryIO

from ...artifact_retention_cli import load_policy
from ...errors import ValidationError, WeaveFrontendError
from ...mcp_artifact_storage import artifact_reconciliation
from ...runtime_container import close_runtime_services
from .service import ArtifactQuarantineService

MAX_ARTIFACT_QUARANTINE_PLAN_BYTES = 16 * 1024 * 1024


def build_parser() -> argparse.ArgumentParser:
    """Build the operator-only quarantine publication parser."""

    parser = argparse.ArgumentParser(
        prog="weave-artifact-quarantine",
        description=(
            "Move one exact retention-plan entry into verified quarantine. "
            "This command never permanently deletes artifacts."
        ),
    )
    parser.add_argument(
        "--policy",
        required=True,
        help="retention policy JSON path, or '-' for standard input",
    )
    parser.add_argument(
        "--plan",
        required=True,
        help="exact retention plan JSON path, or '-' for standard input",
    )
    parser.add_argument(
        "--entry-id",
        required=True,
        help="opaque selected entry identity from the exact retention plan",
    )
    return parser


def _read_bounded(stream: BinaryIO) -> bytes:
    payload = stream.read(MAX_ARTIFACT_QUARANTINE_PLAN_BYTES + 1)
    if len(payload) > MAX_ARTIFACT_QUARANTINE_PLAN_BYTES:
        raise ValidationError(
            "ARTIFACT_QUARANTINE_PLAN_TOO_LARGE",
            "retention plan exceeds the bounded input size",
        )
    return payload


def load_plan(value: str) -> Mapping[str, Any]:
    """Read one bounded UTF-8 JSON retention plan."""

    try:
        if value == "-":
            payload = _read_bounded(sys.stdin.buffer)
        else:
            with Path(value).open("rb") as stream:
                payload = _read_bounded(stream)
    except OSError as exc:
        raise ValidationError(
            "ARTIFACT_QUARANTINE_PLAN_UNAVAILABLE",
            "cannot read the retention plan",
        ) from exc
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(
            "ARTIFACT_QUARANTINE_PLAN_INVALID",
            "retention plan must be valid UTF-8 JSON",
        ) from exc
    if not isinstance(decoded, Mapping):
        raise ValidationError(
            "ARTIFACT_QUARANTINE_PLAN_INVALID",
            "retention plan must be a JSON object",
        )
    return decoded


def generate_quarantine(
    policy: Mapping[str, Any],
    plan: Mapping[str, Any],
    *,
    entry_id: str,
) -> dict[str, Any]:
    """Publish one quarantine capsule through production reconciliation."""

    return ArtifactQuarantineService(artifact_reconciliation()).quarantine(
        policy,
        plan,
        entry_id=entry_id,
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
    """Print verified quarantine evidence or one structured domain error."""

    args = build_parser().parse_args()
    try:
        if args.policy == "-" and args.plan == "-":
            raise ValidationError(
                "ARTIFACT_QUARANTINE_INPUT_CONFLICT",
                "policy and plan cannot both use standard input",
            )
        policy = load_policy(args.policy)
        plan = load_plan(args.plan)
        result = generate_quarantine(
            policy,
            plan,
            entry_id=args.entry_id,
        )
    except WeaveFrontendError as exc:
        print(
            json.dumps(_error_payload(exc), indent=2, sort_keys=True),
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    finally:
        close_runtime_services()
    print(json.dumps(result, indent=2, sort_keys=True))


__all__ = [
    "MAX_ARTIFACT_QUARANTINE_PLAN_BYTES",
    "build_parser",
    "generate_quarantine",
    "load_plan",
    "main",
]


if __name__ == "__main__":
    main()
