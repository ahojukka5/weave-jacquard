"""Command-line semantic compatibility diffing for Jacquard evidence."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .compiler import MAX_COMPILER_PROTOCOL_BYTES, CompilerFileTooLarge, read_bounded_json
from .manifest_compatibility import (
    ManifestCompatibilityError,
    compare_manifests,
)
from .runtime_evidence_compatibility import (
    RUNTIME_IDENTITY_FORMAT,
    SERVICE_GRAPH_FORMAT,
    RuntimeEvidenceCompatibilityError,
    compare_runtime_evidence,
)

MAX_MANIFEST_BYTES = MAX_COMPILER_PROTOCOL_BYTES


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="weave-manifest-diff")
    parser.add_argument("old_manifest", type=Path)
    parser.add_argument("new_manifest", nargs="?", type=Path)
    parser.add_argument(
        "--installed",
        choices=("tool", "application"),
        help="compare the old manifest with the currently installed public contract",
    )
    return parser


def _read_manifest(path: Path) -> Mapping[str, Any]:
    try:
        document = read_bounded_json(path, max_bytes=MAX_MANIFEST_BYTES)
    except CompilerFileTooLarge as exc:
        raise ManifestCompatibilityError(str(exc)) from exc
    except UnicodeDecodeError as exc:
        raise ManifestCompatibilityError(f"manifest {path.name!r} is not valid UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise ManifestCompatibilityError(
            f"manifest {path.name!r} has invalid JSON at line {exc.lineno}, column {exc.colno}"
        ) from exc
    except OSError as exc:
        reason = exc.strerror or type(exc).__name__
        raise ManifestCompatibilityError(f"cannot read manifest {path.name!r}: {reason}") from exc
    if not isinstance(document, Mapping):
        raise ManifestCompatibilityError(f"manifest {path.name!r} must contain a JSON object")
    return document


def _installed_manifest(kind: str) -> Mapping[str, Any]:
    from weave_jacquard.mcp_build import (
        PUBLIC_APPLICATION_MANIFEST,
        PUBLIC_TOOL_MANIFEST,
    )

    if kind == "tool":
        return PUBLIC_TOOL_MANIFEST
    if kind == "application":
        return PUBLIC_APPLICATION_MANIFEST
    raise ManifestCompatibilityError(f"unsupported installed manifest {kind!r}")


def _compare_documents(
    old_document: Mapping[str, Any],
    new_document: Mapping[str, Any],
) -> dict[str, Any]:
    runtime_formats = {SERVICE_GRAPH_FORMAT, RUNTIME_IDENTITY_FORMAT}
    if (
        old_document.get("format") in runtime_formats
        or new_document.get("format") in runtime_formats
    ):
        try:
            return compare_runtime_evidence(old_document, new_document)
        except RuntimeEvidenceCompatibilityError as exc:
            raise ManifestCompatibilityError(str(exc)) from exc
    return compare_manifests(old_document, new_document)


def compare_manifest_files(
    old_path: Path,
    new_path: Path | None = None,
    *,
    installed: str | None = None,
) -> dict[str, Any]:
    """Compare bounded files or one file against the installed public contract."""

    if new_path is None and installed is None:
        raise ManifestCompatibilityError("new_manifest or --installed is required")
    if new_path is not None and installed is not None:
        raise ManifestCompatibilityError("new_manifest cannot be used with --installed")
    old_document = _read_manifest(old_path)
    new_document = (
        _read_manifest(new_path) if new_path is not None else _installed_manifest(str(installed))
    )
    return _compare_documents(old_document, new_document)


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
        report = compare_manifest_files(
            args.old_manifest,
            args.new_manifest,
            installed=args.installed,
        )
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
