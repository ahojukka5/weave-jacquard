"""Operator CLI for deterministic retained-artifact reconciliation."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .errors import ValidationError, WeaveFrontendError
from .mcp_artifact_storage import artifact_reconciliation
from .runtime_container import close_runtime_services


def build_parser() -> argparse.ArgumentParser:
    """Build the standalone reconciliation report parser."""

    return argparse.ArgumentParser(
        prog="weave-artifact-reconcile",
        description=(
            "Inspect the configured database and retained artifact roots without "
            "repairing, moving, or deleting evidence."
        ),
    )


def generate_report() -> dict[str, Any]:
    """Generate one complete report through the production runtime service."""

    return artifact_reconciliation().report()


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
    """Print one deterministic JSON report or one structured domain error."""

    build_parser().parse_args()
    try:
        report = generate_report()
    except WeaveFrontendError as exc:
        print(
            json.dumps(_error_payload(exc), indent=2, sort_keys=True),
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    finally:
        close_runtime_services()
    print(json.dumps(report, indent=2, sort_keys=True))


__all__ = [
    "build_parser",
    "generate_report",
    "main",
]


if __name__ == "__main__":
    main()
