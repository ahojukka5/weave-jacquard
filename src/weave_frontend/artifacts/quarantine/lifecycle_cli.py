"""Operator CLIs for quarantine verification and guarded deletion batches."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, BinaryIO

from ...errors import ValidationError, WeaveFrontendError
from ...mcp_artifact_storage import artifact_reconciliation
from ...runtime_container import close_runtime_services
from .deletion_batch import (
    ArtifactQuarantineDeleteBatchService,
)
from .verification import (
    ArtifactQuarantineVerificationService,
)

ARTIFACT_QUARANTINE_DELETE_REQUEST_FORMAT = "weave-artifact-quarantine-delete-request-v1"
MAX_ARTIFACT_QUARANTINE_DELETE_REQUEST_BYTES = 16 * 1024 * 1024


def build_verification_parser() -> argparse.ArgumentParser:
    """Build the exact read-only quarantine verification parser."""

    parser = argparse.ArgumentParser(
        prog="weave-artifact-quarantine-verify",
        description=(
            "Reverify one exact quarantine capsule and its explicit holding "
            "period without mutating retained storage."
        ),
    )
    parser.add_argument("--quarantine-id", required=True)
    parser.add_argument("--manifest-id", required=True)
    parser.add_argument("--plan-id", required=True)
    parser.add_argument(
        "--minimum-holding-seconds",
        required=True,
        type=int,
    )
    parser.add_argument(
        "--as-of-unix-ns",
        required=True,
        type=int,
        help="explicit deterministic verification timestamp",
    )
    return parser


def build_delete_parser() -> argparse.ArgumentParser:
    """Build the bounded explicit permanent-delete batch parser."""

    parser = argparse.ArgumentParser(
        prog="weave-artifact-quarantine-delete",
        description=(
            "Permanently delete an explicit bounded batch of exact verified "
            "quarantine capsules. This operation is irreversible."
        ),
    )
    parser.add_argument(
        "--request",
        required=True,
        help="delete request JSON path, or '-' for standard input",
    )
    return parser


def generate_verification(
    *,
    quarantine_id: str,
    manifest_id: str,
    plan_id: str,
    minimum_holding_seconds: int,
    as_of_unix_ns: int,
) -> dict[str, Any]:
    """Verify through the production reconciliation and retained family graph."""

    return ArtifactQuarantineVerificationService(artifact_reconciliation()).verify(
        quarantine_id=quarantine_id,
        manifest_id=manifest_id,
        plan_id=plan_id,
        minimum_holding_seconds=minimum_holding_seconds,
        as_of_unix_ns=as_of_unix_ns,
    )


def generate_delete_batch(entries: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Delete an explicit batch through production reconciliation services."""

    return ArtifactQuarantineDeleteBatchService(artifact_reconciliation()).delete_batch(entries)


def load_delete_request(value: str) -> list[Mapping[str, Any]]:
    """Read one bounded UTF-8 JSON delete request."""

    try:
        if value == "-":
            payload = _read_bounded(sys.stdin.buffer)
        else:
            with Path(value).open("rb") as stream:
                payload = _read_bounded(stream)
    except OSError as exc:
        raise ValidationError(
            "ARTIFACT_QUARANTINE_DELETE_REQUEST_UNAVAILABLE",
            "cannot read the permanent-delete request",
        ) from exc
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(
            "ARTIFACT_QUARANTINE_DELETE_REQUEST_INVALID",
            "permanent-delete request must be valid UTF-8 JSON",
        ) from exc
    if (
        not isinstance(decoded, Mapping)
        or set(decoded) != {"format", "entries"}
        or decoded["format"] != ARTIFACT_QUARANTINE_DELETE_REQUEST_FORMAT
        or not isinstance(decoded["entries"], list)
    ):
        raise ValidationError(
            "ARTIFACT_QUARANTINE_DELETE_REQUEST_INVALID",
            "permanent-delete request has invalid or missing fields",
        )
    return decoded["entries"]


def verification_main() -> None:
    """Print exact read-only verification evidence or a structured error."""

    args = build_verification_parser().parse_args()
    try:
        result = generate_verification(
            quarantine_id=args.quarantine_id,
            manifest_id=args.manifest_id,
            plan_id=args.plan_id,
            minimum_holding_seconds=args.minimum_holding_seconds,
            as_of_unix_ns=args.as_of_unix_ns,
        )
    except WeaveFrontendError as exc:
        _print_error(exc)
        raise SystemExit(2) from None
    finally:
        close_runtime_services()
    print(json.dumps(result, indent=2, sort_keys=True))


def delete_main() -> None:
    """Print ordered batch evidence and fail the process on partial completion."""

    args = build_delete_parser().parse_args()
    try:
        entries = load_delete_request(args.request)
        result = generate_delete_batch(entries)
    except WeaveFrontendError as exc:
        _print_error(exc)
        raise SystemExit(2) from None
    finally:
        close_runtime_services()
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["complete"] is not True:
        raise SystemExit(3)


def _read_bounded(stream: BinaryIO) -> bytes:
    payload = stream.read(MAX_ARTIFACT_QUARANTINE_DELETE_REQUEST_BYTES + 1)
    if len(payload) > MAX_ARTIFACT_QUARANTINE_DELETE_REQUEST_BYTES:
        raise ValidationError(
            "ARTIFACT_QUARANTINE_DELETE_REQUEST_TOO_LARGE",
            "permanent-delete request exceeds the bounded input size",
        )
    return payload


def _print_error(exc: WeaveFrontendError) -> None:
    if isinstance(exc, ValidationError):
        error = exc.as_dict()
    else:
        error = {"code": type(exc).__name__, "message": str(exc)}
    print(
        json.dumps({"ok": False, "error": error}, indent=2, sort_keys=True),
        file=sys.stderr,
    )


__all__ = [
    "ARTIFACT_QUARANTINE_DELETE_REQUEST_FORMAT",
    "MAX_ARTIFACT_QUARANTINE_DELETE_REQUEST_BYTES",
    "build_delete_parser",
    "build_verification_parser",
    "delete_main",
    "generate_delete_batch",
    "generate_verification",
    "load_delete_request",
    "verification_main",
]
