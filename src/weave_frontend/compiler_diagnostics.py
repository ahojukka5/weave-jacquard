"""Validation and node mapping for ``weavec-diagnostics-v1`` documents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .source_map import smallest_node_for_span


COMPILER_DIAGNOSTICS_FORMAT = "weavec-diagnostics-v1"
BUILD_DIAGNOSTICS_FORMAT = "weave-build-diagnostics-v1"


def collect_build_diagnostics(
    compiler_diagnostics_path: Path,
    *,
    node_map: dict[str, Any],
    canonical_source_path: Path,
    returncode: int | None,
    timed_out: bool,
    stdout: str,
    stderr: str,
) -> tuple[dict[str, Any], bool]:
    """Return mapped bridge diagnostics and compiler-protocol validity.

    A compiler document is treated as a protocol boundary rather than trusted
    arbitrary JSON. Invalid or missing output becomes a structured bridge
    diagnostic and never raises out of the build operation.
    """

    compiler_document: dict[str, Any] | None = None
    protocol_errors: list[str] = []
    entries: list[dict[str, Any]] = []

    if compiler_diagnostics_path.is_file():
        try:
            value = json.loads(compiler_diagnostics_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            protocol_errors.append(f"cannot read compiler diagnostics: {exc}")
        else:
            if isinstance(value, dict):
                compiler_document = value
                protocol_errors.extend(_validate_document(value, returncode=returncode))
                if not protocol_errors:
                    entries = [
                        _map_entry(
                            entry,
                            node_map=node_map,
                            canonical_source_path=canonical_source_path,
                        )
                        for entry in value["diagnostics"]
                    ]
            else:
                protocol_errors.append("compiler diagnostics root must be an object")
    elif timed_out:
        protocol_errors.append("compiler timed out before writing diagnostics")
    elif returncode is None:
        protocol_errors.append("compiler process did not start")
    else:
        protocol_errors.append("compiler did not write diagnostics")

    protocol_valid = not protocol_errors
    if not protocol_valid:
        entries.append(
            _bridge_protocol_entry(
                protocol_errors,
                timed_out=timed_out,
                returncode=returncode,
            )
        )

    compiler_summary: dict[str, Any] | None = None
    if compiler_document is not None:
        compiler_summary = {
            key: compiler_document.get(key)
            for key in (
                "format",
                "status",
                "phase",
                "exit_code",
                "raw_exit_code",
            )
        }

    diagnostics = {
        "format": BUILD_DIAGNOSTICS_FORMAT,
        "returncode": returncode,
        "timed_out": timed_out,
        "stdout": stdout,
        "stderr": stderr,
        "compiler": compiler_summary,
        "protocol_valid": protocol_valid,
        "protocol_errors": protocol_errors,
        "entries": entries,
    }
    return diagnostics, protocol_valid


def _validate_document(
    document: dict[str, Any],
    *,
    returncode: int | None,
) -> list[str]:
    errors: list[str] = []
    if document.get("format") != COMPILER_DIAGNOSTICS_FORMAT:
        errors.append(
            f"unsupported compiler diagnostics format: {document.get('format')!r}"
        )
    if document.get("status") not in {"succeeded", "failed"}:
        errors.append("compiler diagnostics status must be 'succeeded' or 'failed'")
    if not isinstance(document.get("phase"), str) or not document["phase"]:
        errors.append("compiler diagnostics phase must be a non-empty string")
    if not _is_int(document.get("exit_code")):
        errors.append("compiler diagnostics exit_code must be an integer")
    if not _is_int(document.get("raw_exit_code")):
        errors.append("compiler diagnostics raw_exit_code must be an integer")
    if returncode is not None and document.get("exit_code") != returncode:
        errors.append(
            "compiler diagnostics exit_code does not match process return code"
        )

    raw_entries = document.get("diagnostics")
    if not isinstance(raw_entries, list):
        errors.append("compiler diagnostics diagnostics must be an array")
        return errors

    for index, entry in enumerate(raw_entries):
        errors.extend(_validate_entry(entry, index=index))
    return errors


def _validate_entry(value: Any, *, index: int) -> list[str]:
    prefix = f"diagnostic {index}"
    if not isinstance(value, dict):
        return [f"{prefix} must be an object"]

    errors: list[str] = []
    for key in ("code", "severity", "phase", "message", "span_origin"):
        if not isinstance(value.get(key), str) or not value[key]:
            errors.append(f"{prefix} {key} must be a non-empty string")
    source = value.get("source")
    if source is not None and not isinstance(source, str):
        errors.append(f"{prefix} source must be a string or null")

    span = value.get("span")
    if span is not None:
        if not isinstance(span, dict):
            errors.append(f"{prefix} span must be an object or null")
        else:
            required = (
                "start_byte",
                "end_byte",
                "start_line",
                "start_column",
                "end_line",
                "end_column",
            )
            for key in required:
                if not _is_int(span.get(key)):
                    errors.append(f"{prefix} span {key} must be an integer")
            if all(_is_int(span.get(key)) for key in required):
                if span["start_byte"] < 0 or span["end_byte"] < span["start_byte"]:
                    errors.append(f"{prefix} span has invalid byte bounds")
                if min(
                    span["start_line"],
                    span["start_column"],
                    span["end_line"],
                    span["end_column"],
                ) < 1:
                    errors.append(f"{prefix} span line and column values are one-based")
    return errors


def _map_entry(
    entry: dict[str, Any],
    *,
    node_map: dict[str, Any],
    canonical_source_path: Path,
) -> dict[str, Any]:
    mapped = dict(entry)
    mapped["compiler_source"] = entry.get("source")
    mapped["node_id"] = None

    if not _refers_to_canonical_source(entry.get("source"), canonical_source_path):
        return mapped

    mapped["source"] = canonical_source_path.name
    span = entry.get("span")
    if span is None:
        return mapped

    source_size = canonical_source_path.stat().st_size
    start_byte = int(span["start_byte"])
    end_byte = int(span["end_byte"])
    if start_byte > source_size or end_byte > source_size:
        mapped["mapping_error"] = "compiler span exceeds canonical source length"
        return mapped

    mapped["node_id"] = smallest_node_for_span(
        node_map,
        start_byte=start_byte,
        end_byte=end_byte,
    )
    return mapped


def _refers_to_canonical_source(value: Any, canonical_source_path: Path) -> bool:
    if not isinstance(value, str) or not value:
        return False
    candidate = Path(value)
    if candidate.is_absolute():
        try:
            return candidate.resolve() == canonical_source_path.resolve()
        except OSError:
            return False
    return candidate.as_posix() in {
        canonical_source_path.name,
        f"./{canonical_source_path.name}",
    }


def _bridge_protocol_entry(
    errors: list[str],
    *,
    timed_out: bool,
    returncode: int | None,
) -> dict[str, Any]:
    if timed_out:
        code = "bridge.compiler-timeout"
        message = "weavec build timed out before producing valid diagnostics"
    elif returncode is None:
        code = "bridge.compiler-launch-failed"
        message = "weavec build could not be started"
    else:
        code = "bridge.invalid-compiler-diagnostics"
        message = "weavec produced missing or invalid machine-readable diagnostics"
    return {
        "code": code,
        "severity": "error",
        "phase": "bridge",
        "message": message,
        "source": None,
        "compiler_source": None,
        "span_origin": "none",
        "span": None,
        "node_id": None,
        "details": list(errors),
    }


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
