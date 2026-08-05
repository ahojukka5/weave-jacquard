#!/usr/bin/env python3
"""Retain canonical public Jacquard manifests in qualification evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

MANIFEST_INDEX_FORMAT = "weave-jacquard-release-manifest-index-v1"
QUALIFICATION_COMPLETION_FORMAT = "weave-jacquard-qualification-complete-v1"
MAX_MANIFEST_BYTES = 16 * 1024 * 1024


class ManifestEvidenceError(RuntimeError):
    """Raised when public release manifests cannot be retained safely."""


def _public_manifests() -> tuple[Mapping[str, Any], Mapping[str, Any], Sequence[Any]]:
    from weave_jacquard.mcp_build import (
        PUBLIC_APPLICATION_MANIFEST,
        PUBLIC_CAPABILITY_MANIFEST,
        PUBLIC_TOOL_MANIFEST,
    )

    return (
        PUBLIC_TOOL_MANIFEST,
        PUBLIC_APPLICATION_MANIFEST,
        PUBLIC_CAPABILITY_MANIFEST,
    )


def _canonical_bytes(value: Any) -> bytes:
    try:
        encoded = (
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
            + b"\n"
        )
    except (TypeError, ValueError) as exc:
        raise ManifestEvidenceError(f"manifest is not canonical JSON: {exc}") from exc
    if len(encoded) > MAX_MANIFEST_BYTES:
        raise ManifestEvidenceError(
            f"manifest is {len(encoded)} bytes; limit is {MAX_MANIFEST_BYTES}"
        )
    return encoded


def _require_sha256(value: Any, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ManifestEvidenceError(f"{label} must be a lowercase SHA-256 identity")
    return value


def _read_completion(out: Path) -> Mapping[str, Any]:
    completion_path = out / "qualification-complete.json"
    try:
        document = json.loads(completion_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestEvidenceError(
            "qualification completion evidence is missing or invalid"
        ) from exc
    if not isinstance(document, Mapping):
        raise ManifestEvidenceError("qualification completion evidence must be an object")
    if document.get("format") != QUALIFICATION_COMPLETION_FORMAT:
        raise ManifestEvidenceError("qualification completion format is unsupported")
    if document.get("status") != "passed":
        raise ManifestEvidenceError("public manifests require passed qualification")
    return document


def retain_public_manifests(out: Path) -> dict[str, Any]:
    """Write canonical public manifests and a content-addressed evidence index."""

    candidate = out.expanduser()
    if candidate.is_symlink():
        raise ManifestEvidenceError("qualification output must not be a symlink")
    output = candidate.resolve()
    if not output.is_dir():
        raise ManifestEvidenceError("qualification output must be an existing directory")
    completion = _read_completion(output)
    tool_manifest, application_manifest, capability_manifest = _public_manifests()
    if not isinstance(tool_manifest, Mapping) or not isinstance(application_manifest, Mapping):
        raise ManifestEvidenceError("public tool and application manifests must be objects")
    if not isinstance(capability_manifest, Sequence) or isinstance(
        capability_manifest, (str, bytes, bytearray)
    ):
        raise ManifestEvidenceError("public capability manifest must be a sequence")
    if tool_manifest.get("format") != "weave-jacquard-tool-manifest-v2":
        raise ManifestEvidenceError("public tool manifest format is unsupported")
    if application_manifest.get("format") != "weave-jacquard-application-v2":
        raise ManifestEvidenceError("public application manifest format is unsupported")

    tool_id = _require_sha256(
        tool_manifest.get("tool_manifest_id"),
        label="tool_manifest_id",
    )
    application_id = _require_sha256(
        application_manifest.get("application_id"),
        label="application_id",
    )
    if application_manifest.get("tool_manifest_id") != tool_id:
        raise ManifestEvidenceError(
            "application manifest does not reference the retained tool manifest"
        )
    if application_manifest.get("tool_count") != tool_manifest.get("tool_count"):
        raise ManifestEvidenceError("application and tool manifests disagree about tool_count")

    manifest_root = output / "manifests"
    if manifest_root.exists() or manifest_root.is_symlink():
        raise ManifestEvidenceError("manifest evidence already exists")
    manifest_root.mkdir()

    documents = (
        (
            "tool",
            manifest_root / "tool-manifest.json",
            tool_manifest,
            tool_manifest.get("format"),
            tool_id,
        ),
        (
            "application",
            manifest_root / "application-manifest.json",
            application_manifest,
            application_manifest.get("format"),
            application_id,
        ),
        (
            "capability",
            manifest_root / "capability-manifest.json",
            {
                "format": "weave-jacquard-capability-manifest-v1",
                "capabilities": list(capability_manifest),
            },
            "weave-jacquard-capability-manifest-v1",
            None,
        ),
    )
    entries: list[dict[str, Any]] = []
    for kind, path, document, document_format, identity in documents:
        if not isinstance(document_format, str) or not document_format:
            raise ManifestEvidenceError(f"{kind} manifest format is missing")
        payload = _canonical_bytes(document)
        path.write_bytes(payload)
        entry = {
            "kind": kind,
            "path": path.relative_to(output).as_posix(),
            "format": document_format,
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        if identity is not None:
            entry["identity"] = identity
        entries.append(entry)

    index = {
        "format": MANIFEST_INDEX_FORMAT,
        "qualification_git_sha": completion.get("git_sha"),
        "tool_manifest_id": tool_id,
        "application_id": application_id,
        "manifest_count": len(entries),
        "manifests": entries,
    }
    (output / "manifest-index.json").write_bytes(_canonical_bytes(index))
    return index


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("qualification_output", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        retain_public_manifests(args.qualification_output)
    except ManifestEvidenceError as exc:
        print(f"release manifest evidence failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
