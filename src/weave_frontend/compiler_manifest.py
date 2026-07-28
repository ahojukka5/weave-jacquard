"""Validation for the public ``weavec-build-manifest-v1`` contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .compiler_io import CompilerFileTooLarge, read_bounded_json
from .compiler_limits import MAX_COMPILER_PROTOCOL_BYTES

COMPILER_MANIFEST_FORMAT = "weavec-build-manifest-v1"


def validate_compiler_manifest(
    path: Path,
    *,
    expected_sources: list[Path],
    expected_output: Path,
    requested_target: str | None,
    returncode: int | None,
    diagnostics_status: str | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Read and validate one compiler manifest without modifying its raw bytes."""

    errors: list[str] = []
    if not path.is_file():
        return None, ["compiler did not write a build manifest"]

    try:
        document = read_bounded_json(path, max_bytes=MAX_COMPILER_PROTOCOL_BYTES)
    except CompilerFileTooLarge as exc:
        return None, [str(exc)]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, [f"cannot read compiler build manifest: {exc}"]
    if not isinstance(document, dict):
        return None, ["compiler build manifest root must be an object"]

    if document.get("format") != COMPILER_MANIFEST_FORMAT:
        errors.append(
            f"unsupported compiler build manifest format: {document.get('format')!r}"
        )

    status = document.get("status")
    if status not in {"succeeded", "failed"}:
        errors.append("compiler build manifest status must be 'succeeded' or 'failed'")
    phase = document.get("phase")
    if not isinstance(phase, str) or not phase:
        errors.append("compiler build manifest phase must be a non-empty string")
    if status == "succeeded" and phase != "complete":
        errors.append("successful compiler build manifest phase must be 'complete'")
    if status == "failed" and phase == "complete":
        errors.append("failed compiler build manifest phase must not be 'complete'")

    expected_status = "succeeded" if returncode == 0 else "failed"
    if status in {"succeeded", "failed"} and status != expected_status:
        errors.append("compiler build manifest status does not match process return code")
    if diagnostics_status in {"succeeded", "failed"} and status != diagnostics_status:
        errors.append("compiler build manifest status does not match compiler diagnostics")

    target = document.get("target")
    if not isinstance(target, str) or not target:
        errors.append("compiler build manifest target must be a non-empty string")
    elif requested_target is not None and target != requested_target:
        errors.append("compiler build manifest target does not match requested target")

    for key in ("compiler", "runtime", "codegen", "linker"):
        if not isinstance(document.get(key), str) or not document[key]:
            errors.append(f"compiler build manifest {key} must be a non-empty string")

    output = _manifest_path(document.get("output"), base=path.parent)
    if output is None:
        errors.append("compiler build manifest output must be a non-empty path")
    elif output != expected_output.resolve():
        errors.append("compiler build manifest output does not match requested executable")

    sources = document.get("sources")
    if not isinstance(sources, list):
        errors.append("compiler build manifest sources must be an array")
    else:
        resolved_sources: list[Path] = []
        for index, value in enumerate(sources):
            resolved = _manifest_path(value, base=path.parent)
            if resolved is None:
                errors.append(
                    f"compiler build manifest source {index} must be a non-empty path"
                )
            else:
                resolved_sources.append(resolved)
        if len(resolved_sources) == len(sources) and resolved_sources != [
            source.resolve() for source in expected_sources
        ]:
            errors.append(
                "compiler build manifest sources do not match ordered compiler inputs"
            )

    return document, errors


def _manifest_path(value: Any, *, base: Path) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    try:
        if path.is_absolute():
            return path.resolve()
        root = base.resolve()
        resolved = (root / path).resolve()
        resolved.relative_to(root)
        return resolved
    except (OSError, ValueError):
        return None
