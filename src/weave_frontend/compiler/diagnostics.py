"""Validation and node mapping for ``weavec-diagnostics-v1`` documents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..source_map import smallest_node_for_span
from .io import CompilerFileTooLarge, read_bounded_json
from .limits import MAX_COMPILER_OUTPUT_BYTES, MAX_COMPILER_PROTOCOL_BYTES

COMPILER_DIAGNOSTICS_FORMAT = "weavec-diagnostics-v1"
BUILD_DIAGNOSTICS_FORMAT = "weave-build-diagnostics-v1"
SPAN_ORIGINS = {
    "compiler-preflight",
    "propagated-wir-location",
    "inferred-unique-token",
    "none",
}


def collect_build_diagnostics(
    compiler_diagnostics_path: Path,
    *,
    returncode: int | None,
    timed_out: bool,
    output_limited: bool = False,
    stdout: str,
    stderr: str,
    canonical_sources: list[tuple[Path, dict[str, Any]]] | None = None,
    node_map: dict[str, Any] | None = None,
    canonical_source_path: Path | None = None,
    compiler_output_limit_bytes: int = MAX_COMPILER_OUTPUT_BYTES,
) -> tuple[dict[str, Any], bool]:
    """Return mapped bridge diagnostics and compiler-protocol validity.

    ``canonical_sources`` is the ordered set of compiler inputs and their node
    maps. The legacy single-source keyword pair remains accepted for callers
    that build one document.
    """

    sources = _normalize_canonical_sources(
        canonical_sources=canonical_sources,
        node_map=node_map,
        canonical_source_path=canonical_source_path,
    )
    compiler_document: dict[str, Any] | None = None
    protocol_errors: list[str] = []
    entries: list[dict[str, Any]] = []

    if output_limited:
        protocol_errors.append("compiler output exceeded the configured byte limit")
    if timed_out:
        protocol_errors.append("compiler timed out before completing")

    if compiler_diagnostics_path.is_file():
        try:
            value = read_bounded_json(
                compiler_diagnostics_path,
                max_bytes=MAX_COMPILER_PROTOCOL_BYTES,
            )
        except CompilerFileTooLarge as exc:
            protocol_errors.append(str(exc))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            protocol_errors.append(f"cannot read compiler diagnostics: {exc}")
        else:
            if isinstance(value, dict):
                compiler_document = value
                validation_errors = _validate_document(value, returncode=returncode)
                protocol_errors.extend(validation_errors)
                if not protocol_errors:
                    entries = [
                        _map_entry(entry, canonical_sources=sources)
                        for entry in value["diagnostics"]
                    ]
            else:
                protocol_errors.append("compiler diagnostics root must be an object")
    elif not timed_out and not output_limited and returncode is None:
        protocol_errors.append("compiler process did not start")
    elif not timed_out and not output_limited:
        protocol_errors.append("compiler did not write diagnostics")

    protocol_valid = not protocol_errors
    if not protocol_valid:
        entries.append(
            _bridge_protocol_entry(
                protocol_errors,
                timed_out=timed_out,
                output_limited=output_limited,
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
        "output_limited": output_limited,
        "compiler_output_limit_bytes": compiler_output_limit_bytes,
        "compiler_protocol_limit_bytes": MAX_COMPILER_PROTOCOL_BYTES,
        "stdout": stdout,
        "stderr": stderr,
        "compiler": compiler_summary,
        "protocol_valid": protocol_valid,
        "protocol_errors": protocol_errors,
        "entries": entries,
    }
    return diagnostics, protocol_valid


def _normalize_canonical_sources(
    *,
    canonical_sources: list[tuple[Path, dict[str, Any]]] | None,
    node_map: dict[str, Any] | None,
    canonical_source_path: Path | None,
) -> list[tuple[Path, dict[str, Any]]]:
    if canonical_sources is not None:
        if node_map is not None or canonical_source_path is not None:
            raise ValueError(
                "use canonical_sources or the legacy single-source arguments, not both"
            )
        if not canonical_sources:
            raise ValueError("at least one canonical source is required")
        return list(canonical_sources)
    if node_map is None or canonical_source_path is None:
        raise ValueError("canonical source path and node map are required")
    return [(canonical_source_path, node_map)]


def _validate_document(
    document: dict[str, Any],
    *,
    returncode: int | None,
) -> list[str]:
    errors: list[str] = []
    if document.get("format") != COMPILER_DIAGNOSTICS_FORMAT:
        errors.append(f"unsupported compiler diagnostics format: {document.get('format')!r}")

    status = document.get("status")
    if status not in {"succeeded", "failed"}:
        errors.append("compiler diagnostics status must be 'succeeded' or 'failed'")
    phase = document.get("phase")
    if not isinstance(phase, str) or not phase:
        errors.append("compiler diagnostics phase must be a non-empty string")

    exit_code = document.get("exit_code")
    if not _is_int(exit_code):
        errors.append("compiler diagnostics exit_code must be an integer")
    raw_exit_code = document.get("raw_exit_code")
    if not _is_int(raw_exit_code):
        errors.append("compiler diagnostics raw_exit_code must be an integer")
    if returncode is not None and exit_code != returncode:
        errors.append("compiler diagnostics exit_code does not match process return code")
    if _is_int(exit_code) and status in {"succeeded", "failed"}:
        expected_status = "succeeded" if exit_code == 0 else "failed"
        if status != expected_status:
            errors.append("compiler diagnostics status does not match its exit_code")

    raw_entries = document.get("diagnostics")
    if not isinstance(raw_entries, list):
        errors.append("compiler diagnostics diagnostics must be an array")
        return errors

    if status == "succeeded":
        if phase != "complete":
            errors.append("successful compiler diagnostics phase must be 'complete'")
        if raw_entries:
            errors.append("successful compiler diagnostics must have no entries")
        if _is_int(raw_exit_code) and raw_exit_code != 0:
            errors.append("successful compiler diagnostics raw_exit_code must be zero")
    elif status == "failed":
        if not raw_entries:
            errors.append("failed compiler diagnostics must contain an entry")
        if _is_int(raw_exit_code) and raw_exit_code == 0:
            errors.append("failed compiler diagnostics raw_exit_code must be non-zero")

    for index, entry in enumerate(raw_entries):
        errors.extend(_validate_entry(entry, index=index))
    return errors


def _validate_entry(value: Any, *, index: int) -> list[str]:
    prefix = f"diagnostic {index}"
    if not isinstance(value, dict):
        return [f"{prefix} must be an object"]

    errors: list[str] = []
    for key in ("code", "phase", "message"):
        if not isinstance(value.get(key), str) or not value[key]:
            errors.append(f"{prefix} {key} must be a non-empty string")

    severity = value.get("severity")
    if severity != "error":
        errors.append(f"{prefix} severity must be 'error'")

    source = value.get("source")
    if source is not None and not isinstance(source, str):
        errors.append(f"{prefix} source must be a string or null")

    span_origin = value.get("span_origin")
    if span_origin not in SPAN_ORIGINS:
        errors.append(f"{prefix} span_origin must be one of {sorted(SPAN_ORIGINS)}")

    span = value.get("span")
    if span_origin == "none" and span is not None:
        errors.append(f"{prefix} span must be null when span_origin is 'none'")
    if (
        span_origin
        in {
            "compiler-preflight",
            "propagated-wir-location",
            "inferred-unique-token",
        }
        and span is None
    ):
        errors.append(f"{prefix} span is required for span_origin {span_origin!r}")

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
                if (
                    min(
                        span["start_line"],
                        span["start_column"],
                        span["end_line"],
                        span["end_column"],
                    )
                    < 1
                ):
                    errors.append(f"{prefix} span line and column values are one-based")
    return errors


def _map_entry(
    entry: dict[str, Any],
    *,
    canonical_sources: list[tuple[Path, dict[str, Any]]],
) -> dict[str, Any]:
    mapped = dict(entry)
    mapped["compiler_source"] = entry.get("source")
    mapped["document"] = None
    mapped["node_id"] = None

    selected = _select_canonical_source(entry.get("source"), canonical_sources)
    if selected is None:
        return mapped
    canonical_source_path, node_map = selected

    mapped["source"] = canonical_source_path.name
    mapped["compiler_source"] = canonical_source_path.name
    mapped["document"] = node_map.get("document")
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


def _select_canonical_source(
    value: Any,
    canonical_sources: list[tuple[Path, dict[str, Any]]],
) -> tuple[Path, dict[str, Any]] | None:
    if not isinstance(value, str) or not value:
        return None
    candidate = Path(value)
    if candidate.is_absolute():
        try:
            resolved = candidate.resolve()
        except OSError:
            return None
        for source_path, node_map in canonical_sources:
            try:
                if source_path.resolve() == resolved:
                    return source_path, node_map
            except OSError:
                continue
        return None

    basename = candidate.name
    matches = [
        (source_path, node_map)
        for source_path, node_map in canonical_sources
        if basename == source_path.name
    ]
    return matches[0] if len(matches) == 1 else None


def _bridge_protocol_entry(
    errors: list[str],
    *,
    timed_out: bool,
    output_limited: bool,
    returncode: int | None,
) -> dict[str, Any]:
    if output_limited:
        code = "bridge.compiler-output-limit"
        message = "weavec build exceeded the configured output limit"
    elif timed_out:
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
        "document": None,
        "span_origin": "none",
        "span": None,
        "node_id": None,
        "details": list(errors),
    }


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
