"""Operator CLI for exact restore from retained-artifact quarantine."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from ...errors import ValidationError, WeaveFrontendError
from ...mcp_artifact_storage import artifact_reconciliation
from ...runtime import close_runtime_services
from .restoration import ArtifactQuarantineRestoreService


def build_parser() -> argparse.ArgumentParser:
    """Build the operator-only quarantine restore parser."""

    parser = argparse.ArgumentParser(
        prog="weave-artifact-quarantine-restore",
        description=(
            "Restore one exact verified quarantine capsule to its original "
            "retained-artifact name. This command never deletes artifact payloads."
        ),
    )
    parser.add_argument(
        "--quarantine-id",
        required=True,
        help="exact quarantine operation identity",
    )
    parser.add_argument(
        "--manifest-id",
        required=True,
        help="exact verified quarantine manifest identity",
    )
    return parser


def generate_restore(
    *,
    quarantine_id: str,
    manifest_id: str,
) -> dict[str, Any]:
    """Restore through the production reconciliation and family graph."""

    return ArtifactQuarantineRestoreService(artifact_reconciliation()).restore(
        quarantine_id=quarantine_id,
        manifest_id=manifest_id,
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
    """Print verified restore evidence or one structured domain error."""

    args = build_parser().parse_args()
    try:
        result = generate_restore(
            quarantine_id=args.quarantine_id,
            manifest_id=args.manifest_id,
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


__all__ = ["build_parser", "generate_restore", "main"]


if __name__ == "__main__":
    main()
