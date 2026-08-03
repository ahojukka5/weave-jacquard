"""Command-line semantic compatibility diffing for Jacquard manifests."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .compiler_io import CompilerFileTooLarge, read_bounded_json
from .compiler_limits import MAX_COMPILER_PROTOCOL_BYTES
from .manifest_compatibility import (
    ManifestCompatibilityError,
    compare_tool_manifests,
)

MAX_MANIFEST_BYTES = MAX_COMPILER_PROTOCOL_BYTES


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="weave-manifest-diff")
    parser.add_argument("old_manifest", type=Path)
    parser.add_argument("new_manifest", type=Path)
    return parser


def _read_manifest(path: Path) -> Mapping[str, Any]:
    try:
        document = read_bounded_json(path, max_bytes=MAX_MANIFEST_BYTES)
    except CompilerFileTooLarge as exc:
        raise ManifestCompatibilityError(str(exc)) from exc
    except UnicodeDecodeError as exc:
        raise ManifestCompatibilityError(
            f"manifest {path.name!r} is not valid UTF-8"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ManifestCompatibilityError(
            f"manifest {path.name!r} has invalid JSON at "
            f"line {exc.lineno}, column {exc.colno}"
        ) from exc
    except OSError as exc:
        reason = exc.strerror or type(exc).__name__
        raise ManifestCompatibilityError(
            f"cannot read manifest {path.name!r}: {reason}"
        ) from exc
    if not isinstance(document, Mapping):
        raise ManifestCompatibilityError(
            f"manifest {path.name!r} must contain a JSON object"
        )
    return document


def compare_manifest_files(old_path: Path, new_path: Path) -> dict[str, Any]:
    """Compare two bounded manifest files without opening runtime state."""

    return compare_tool_manifests(
        _read_manifest(old_path),
        _read_manifest(new_path),
    )


def _error_payload(exc: ManifestCompatibilityError) -> dict[str, object]:
    return {
        "ok": False,
        "error": {
            "code": "MANIFEST_COMPATIBILITY_ERROR",
            "message": str(exc),
        },
    }


def main() -> None:
    args = build_parser().parse_args()
    try:
        report = compare_manifest_files(args.old_manifest, args.new_manifest)
    except ManifestCompatibilityError as exc:
        print(json.dumps(_error_payload(exc), indent=2, sort_keys=True), file=sys.stderr)
        raise SystemExit(2) from None
    print(json.dumps(report, indent=2, sort_keys=True))


__all__ = [
    "MAX_MANIFEST_BYTES",
    "build_parser",
    "compare_manifest_files",
    "main",
]


if __name__ == "__main__":
    main()
