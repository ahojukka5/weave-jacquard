"""Bounded semantic codec for retained revision snapshots."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import zlib
from dataclasses import dataclass
from typing import Any

from .errors import ValidationError
from .sexpr import validate_tree

SNAPSHOT_RAW_PREFIX = b"WJR1"
SNAPSHOT_ZLIB_PREFIX = b"WJZ1"
MAX_SNAPSHOT_COMPRESSED_BYTES = 16 * 1024 * 1024
MAX_SNAPSHOT_DECOMPRESSED_BYTES = 32 * 1024 * 1024
MAX_REVISION_MODULES = 4_096
MAX_REVISION_DECODED_BYTES = 256 * 1024 * 1024
MAX_QUALIFIED_NAME_BYTES = 4_096


class SnapshotIntegrityError(ValueError):
    """Raised when retained snapshot evidence violates the storage contract."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        revision_id: str | None = None,
        qualified_name: str | None = None,
        decoded_bytes: int = 0,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.revision_id = revision_id
        self.qualified_name = qualified_name
        self.decoded_bytes = decoded_bytes

    def example(self) -> dict[str, Any]:
        value: dict[str, Any] = {}
        if self.revision_id is not None:
            value["revision_id"] = self.revision_id
        if self.qualified_name is not None:
            value["qualified_name"] = self.qualified_name
        value["message"] = self.message
        return value


@dataclass(frozen=True)
class DecodedSnapshot:
    """One decoded and structurally verified module snapshot."""

    value: dict[str, Any]
    canonical_json: str
    decoded_bytes: int
    ast_hash: str


@dataclass(frozen=True)
class RevisionState:
    """One completely decoded and hash-verified immutable revision state."""

    modules: dict[str, dict[str, Any]]
    module_count: int
    decoded_bytes: int
    root_hash: str


@dataclass(frozen=True)
class RevisionInspection:
    """Complete bounded findings for one admitted revision snapshot set."""

    state: RevisionState | None
    errors: tuple[SnapshotIntegrityError, ...]
    modules_scanned: int
    decoded_bytes: int


def canonical_json(value: Any) -> str:
    """Return the canonical JSON representation used by persisted hashes."""

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def hash_value(value: Any) -> str:
    """Hash one value through the canonical persisted JSON representation."""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def compress_snapshot_json(value: str) -> bytes:
    """Encode one bounded UTF-8 snapshot string for SQLite storage."""

    if not isinstance(value, str):
        raise TypeError("snapshot JSON must be text")
    try:
        raw = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise SnapshotIntegrityError(
            "SNAPSHOT_UTF8_INVALID",
            "snapshot JSON cannot be represented as UTF-8",
        ) from exc
    if len(raw) > MAX_SNAPSHOT_DECOMPRESSED_BYTES:
        raise SnapshotIntegrityError(
            "SNAPSHOT_DECOMPRESSED_LIMIT_EXCEEDED",
            "snapshot JSON exceeds the decompressed-byte limit",
        )
    compressed = zlib.compress(raw, level=3)
    if len(compressed) < len(raw):
        result = SNAPSHOT_ZLIB_PREFIX + compressed
    else:
        result = SNAPSHOT_RAW_PREFIX + raw
    if len(result) > MAX_SNAPSHOT_COMPRESSED_BYTES:
        raise SnapshotIntegrityError(
            "SNAPSHOT_COMPRESSED_LIMIT_EXCEEDED",
            "encoded snapshot exceeds the compressed-byte limit",
        )
    return result


def decompress_snapshot_json(value: bytes | bytearray | memoryview) -> str:
    """Decode one snapshot with strict encoding, stream, and byte ceilings."""

    blob = _snapshot_blob(value)
    if len(blob) > MAX_SNAPSHOT_COMPRESSED_BYTES:
        raise SnapshotIntegrityError(
            "SNAPSHOT_COMPRESSED_LIMIT_EXCEEDED",
            "snapshot blob exceeds the compressed-byte limit",
        )
    if len(blob) < 4:
        raise SnapshotIntegrityError(
            "SNAPSHOT_ENCODING_INVALID",
            "snapshot blob has no supported encoding prefix",
        )

    prefix = blob[:4]
    payload = blob[4:]
    if prefix == SNAPSHOT_RAW_PREFIX:
        raw = payload
        if len(raw) > MAX_SNAPSHOT_DECOMPRESSED_BYTES:
            raise SnapshotIntegrityError(
                "SNAPSHOT_DECOMPRESSED_LIMIT_EXCEEDED",
                "raw snapshot exceeds the decompressed-byte limit",
            )
    elif prefix == SNAPSHOT_ZLIB_PREFIX:
        raw = _bounded_zlib_decompress(payload)
    else:
        raise SnapshotIntegrityError(
            "SNAPSHOT_ENCODING_INVALID",
            "snapshot blob has an unsupported encoding prefix",
        )

    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SnapshotIntegrityError(
            "SNAPSHOT_UTF8_INVALID",
            "snapshot JSON is not valid UTF-8",
            decoded_bytes=len(raw),
        ) from exc


def decode_snapshot(
    value: bytes | bytearray | memoryview,
    *,
    expected_hash: Any,
    revision_id: str | None = None,
    qualified_name: str | None = None,
) -> DecodedSnapshot:
    """Decode, parse, structurally validate, and hash-check one snapshot."""

    try:
        text = decompress_snapshot_json(value)
        return decode_snapshot_text(
            text,
            expected_hash=expected_hash,
            revision_id=revision_id,
            qualified_name=qualified_name,
        )
    except SnapshotIntegrityError as exc:
        if exc.revision_id is None:
            exc.revision_id = revision_id
        if exc.qualified_name is None:
            exc.qualified_name = qualified_name
        raise


def decode_snapshot_text(
    value: str,
    *,
    expected_hash: Any,
    revision_id: str | None = None,
    qualified_name: str | None = None,
) -> DecodedSnapshot:
    """Verify one legacy uncompressed snapshot through the same semantic path."""

    if not isinstance(value, str):
        raise SnapshotIntegrityError(
            "SNAPSHOT_JSON_TYPE_INVALID",
            "snapshot JSON must be text",
            revision_id=revision_id,
            qualified_name=qualified_name,
        )
    try:
        raw = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise SnapshotIntegrityError(
            "SNAPSHOT_UTF8_INVALID",
            "snapshot JSON cannot be represented as UTF-8",
            revision_id=revision_id,
            qualified_name=qualified_name,
        ) from exc
    if len(raw) > MAX_SNAPSHOT_DECOMPRESSED_BYTES:
        raise SnapshotIntegrityError(
            "SNAPSHOT_DECOMPRESSED_LIMIT_EXCEEDED",
            "snapshot JSON exceeds the decompressed-byte limit",
            revision_id=revision_id,
            qualified_name=qualified_name,
        )
    try:
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, RecursionError) as exc:
            raise SnapshotIntegrityError(
                "SNAPSHOT_JSON_INVALID",
                "snapshot JSON cannot be decoded",
                revision_id=revision_id,
                qualified_name=qualified_name,
            ) from exc
        if not isinstance(parsed, dict):
            raise SnapshotIntegrityError(
                "SNAPSHOT_ROOT_INVALID",
                "snapshot root must be a JSON object",
                revision_id=revision_id,
                qualified_name=qualified_name,
            )
        try:
            validate_tree(parsed)
        except (ValidationError, RecursionError) as exc:
            code = exc.code if isinstance(exc, ValidationError) else "TREE_TOO_DEEP"
            raise SnapshotIntegrityError(
                "SNAPSHOT_TREE_INVALID",
                f"snapshot tree violates structural limits: {code}",
                revision_id=revision_id,
                qualified_name=qualified_name,
            ) from exc
        try:
            canonical = canonical_json(parsed)
            canonical_bytes = canonical.encode("utf-8")
        except (TypeError, ValueError, RecursionError, UnicodeEncodeError) as exc:
            raise SnapshotIntegrityError(
                "SNAPSHOT_JSON_INVALID",
                "snapshot value cannot be represented canonically",
                revision_id=revision_id,
                qualified_name=qualified_name,
            ) from exc
        observed_hash = hashlib.sha256(canonical_bytes).hexdigest()
        if not _valid_sha256(expected_hash) or observed_hash != expected_hash:
            raise SnapshotIntegrityError(
                "SNAPSHOT_AST_HASH_MISMATCH",
                "snapshot AST hash does not match decoded canonical state",
                revision_id=revision_id,
                qualified_name=qualified_name,
            )
    except SnapshotIntegrityError as exc:
        exc.decoded_bytes = len(raw)
        raise
    return DecodedSnapshot(
        value=parsed,
        canonical_json=canonical,
        decoded_bytes=len(raw),
        ast_hash=observed_hash,
    )


def inspect_revision_state(
    connection: sqlite3.Connection,
    revision_id: str,
    *,
    expected_root_hash: Any,
    legacy: bool = False,
) -> RevisionInspection:
    """Inspect all admitted snapshots and retain every semantic finding."""

    if legacy:
        cursor = connection.execute(
            """SELECT qualified_name, ast_json, ast_hash
               FROM module_snapshots
               WHERE revision_id = ?
               ORDER BY qualified_name""",
            (revision_id,),
        )
    else:
        cursor = connection.execute(
            """SELECT qualified_name, ast_blob, ast_hash
               FROM module_snapshots_compressed
               WHERE revision_id = ?
               ORDER BY qualified_name""",
            (revision_id,),
        )

    modules: dict[str, dict[str, Any]] = {}
    errors: list[SnapshotIntegrityError] = []
    aggregate_bytes = 0
    modules_scanned = 0
    for index, row in enumerate(cursor):
        if index >= MAX_REVISION_MODULES:
            errors.append(
                SnapshotIntegrityError(
                    "REVISION_MODULE_LIMIT_EXCEEDED",
                    "revision contains more module snapshots than permitted",
                    revision_id=revision_id,
                )
            )
            break
        modules_scanned += 1
        raw_name = row[0]
        if not isinstance(raw_name, str):
            errors.append(
                SnapshotIntegrityError(
                    "REVISION_MODULE_NAME_INVALID",
                    "revision module name must be text",
                    revision_id=revision_id,
                )
            )
            continue
        qualified_name = raw_name
        try:
            _validate_qualified_name(qualified_name, revision_id=revision_id)
        except SnapshotIntegrityError as exc:
            errors.append(exc)
            continue
        if qualified_name in modules:
            errors.append(
                SnapshotIntegrityError(
                    "DUPLICATE_REVISION_MODULE",
                    "revision contains a duplicate qualified module name",
                    revision_id=revision_id,
                    qualified_name=qualified_name,
                )
            )
            continue
        try:
            if legacy:
                decoded = decode_snapshot_text(
                    row[1],
                    expected_hash=row[2],
                    revision_id=revision_id,
                    qualified_name=qualified_name,
                )
            else:
                decoded = decode_snapshot(
                    row[1],
                    expected_hash=row[2],
                    revision_id=revision_id,
                    qualified_name=qualified_name,
                )
        except SnapshotIntegrityError as exc:
            aggregate_bytes += exc.decoded_bytes
            errors.append(exc)
            if aggregate_bytes > MAX_REVISION_DECODED_BYTES:
                errors.append(
                    SnapshotIntegrityError(
                        "REVISION_DECODED_LIMIT_EXCEEDED",
                        "revision snapshot bytes exceed the aggregate decoded-byte limit",
                        revision_id=revision_id,
                    )
                )
                break
            continue
        aggregate_bytes += decoded.decoded_bytes
        if aggregate_bytes > MAX_REVISION_DECODED_BYTES:
            errors.append(
                SnapshotIntegrityError(
                    "REVISION_DECODED_LIMIT_EXCEEDED",
                    "revision snapshot bytes exceed the aggregate decoded-byte limit",
                    revision_id=revision_id,
                )
            )
            break
        modules[qualified_name] = decoded.value

    if not errors:
        observed_root_hash = hash_value(modules)
        if not _valid_sha256(expected_root_hash) or observed_root_hash != expected_root_hash:
            errors.append(
                SnapshotIntegrityError(
                    "REVISION_ROOT_HASH_MISMATCH",
                    "revision root hash does not match reconstructed module state",
                    revision_id=revision_id,
                )
            )
        else:
            return RevisionInspection(
                state=RevisionState(
                    modules=modules,
                    module_count=len(modules),
                    decoded_bytes=aggregate_bytes,
                    root_hash=observed_root_hash,
                ),
                errors=(),
                modules_scanned=modules_scanned,
                decoded_bytes=aggregate_bytes,
            )

    return RevisionInspection(
        state=None,
        errors=tuple(errors),
        modules_scanned=modules_scanned,
        decoded_bytes=aggregate_bytes,
    )


def load_revision_state(
    connection: sqlite3.Connection,
    revision_id: str,
    *,
    expected_root_hash: Any,
    legacy: bool = False,
) -> RevisionState:
    """Load one complete revision or fail without returning partial state."""

    inspection = inspect_revision_state(
        connection,
        revision_id,
        expected_root_hash=expected_root_hash,
        legacy=legacy,
    )
    if inspection.errors:
        raise inspection.errors[0]
    if inspection.state is None:
        raise RuntimeError("revision inspection completed without state or errors")
    return inspection.state


def _snapshot_blob(value: Any) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise SnapshotIntegrityError(
            "SNAPSHOT_BLOB_TYPE_INVALID",
            "snapshot blob must be bytes",
        )
    return bytes(value)


def _bounded_zlib_decompress(payload: bytes) -> bytes:
    decompressor = zlib.decompressobj()
    try:
        raw = decompressor.decompress(
            payload,
            MAX_SNAPSHOT_DECOMPRESSED_BYTES + 1,
        )
    except zlib.error as exc:
        raise SnapshotIntegrityError(
            "SNAPSHOT_COMPRESSION_INVALID",
            "snapshot zlib stream is invalid",
        ) from exc
    if len(raw) > MAX_SNAPSHOT_DECOMPRESSED_BYTES or decompressor.unconsumed_tail:
        raise SnapshotIntegrityError(
            "SNAPSHOT_DECOMPRESSED_LIMIT_EXCEEDED",
            "snapshot zlib output exceeds the decompressed-byte limit",
        )
    try:
        raw += decompressor.flush(MAX_SNAPSHOT_DECOMPRESSED_BYTES + 1 - len(raw))
    except zlib.error as exc:
        raise SnapshotIntegrityError(
            "SNAPSHOT_COMPRESSION_INVALID",
            "snapshot zlib stream cannot be finalized",
        ) from exc
    if len(raw) > MAX_SNAPSHOT_DECOMPRESSED_BYTES:
        raise SnapshotIntegrityError(
            "SNAPSHOT_DECOMPRESSED_LIMIT_EXCEEDED",
            "snapshot zlib output exceeds the decompressed-byte limit",
        )
    if not decompressor.eof:
        raise SnapshotIntegrityError(
            "SNAPSHOT_COMPRESSION_TRUNCATED",
            "snapshot zlib stream ended before its end marker",
        )
    if decompressor.unused_data:
        raise SnapshotIntegrityError(
            "SNAPSHOT_COMPRESSION_TRAILING_DATA",
            "snapshot zlib stream contains trailing bytes",
        )
    return raw


def _validate_qualified_name(value: str, *, revision_id: str) -> None:
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise SnapshotIntegrityError(
            "REVISION_MODULE_NAME_INVALID",
            "revision module name cannot be represented as UTF-8",
            revision_id=revision_id,
        ) from exc
    if not value or "\x00" in value or len(encoded) > MAX_QUALIFIED_NAME_BYTES:
        raise SnapshotIntegrityError(
            "REVISION_MODULE_NAME_INVALID",
            "revision module name is empty, contains NUL, or exceeds the byte limit",
            revision_id=revision_id,
            qualified_name=value,
        )


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = [
    "MAX_QUALIFIED_NAME_BYTES",
    "MAX_REVISION_DECODED_BYTES",
    "MAX_REVISION_MODULES",
    "MAX_SNAPSHOT_COMPRESSED_BYTES",
    "MAX_SNAPSHOT_DECOMPRESSED_BYTES",
    "SNAPSHOT_RAW_PREFIX",
    "SNAPSHOT_ZLIB_PREFIX",
    "DecodedSnapshot",
    "RevisionInspection",
    "RevisionState",
    "SnapshotIntegrityError",
    "canonical_json",
    "compress_snapshot_json",
    "decode_snapshot",
    "decode_snapshot_text",
    "decompress_snapshot_json",
    "hash_value",
    "inspect_revision_state",
    "load_revision_state",
]
