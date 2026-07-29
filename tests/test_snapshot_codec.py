from __future__ import annotations

import sqlite3
import zlib

import pytest

import weave_frontend.snapshot_codec as codec
from weave_frontend.sexpr import make_form
from weave_frontend.snapshot_codec import SnapshotIntegrityError


def _error_code(callable_) -> str:
    with pytest.raises(SnapshotIntegrityError) as captured:
        callable_()
    return captured.value.code


def test_raw_snapshot_accepts_exact_limit_and_rejects_limit_plus_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(codec, "MAX_SNAPSHOT_COMPRESSED_BYTES", 20)
    monkeypatch.setattr(codec, "MAX_SNAPSHOT_DECOMPRESSED_BYTES", 16)

    assert codec.decompress_snapshot_json(b"WJR1" + b"x" * 16) == "x" * 16
    assert _error_code(
        lambda: codec.decompress_snapshot_json(b"WJR1" + b"x" * 17)
    ) == "SNAPSHOT_COMPRESSED_LIMIT_EXCEEDED"


def test_zlib_output_limit_rejects_small_decompression_bomb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(codec, "MAX_SNAPSHOT_COMPRESSED_BYTES", 1_024)
    monkeypatch.setattr(codec, "MAX_SNAPSHOT_DECOMPRESSED_BYTES", 64)
    blob = b"WJZ1" + zlib.compress(b"x" * 65)

    assert _error_code(
        lambda: codec.decompress_snapshot_json(blob)
    ) == "SNAPSHOT_DECOMPRESSED_LIMIT_EXCEEDED"


def test_zlib_stream_rejects_truncation_and_trailing_bytes() -> None:
    payload = zlib.compress(b"payload")

    assert _error_code(
        lambda: codec.decompress_snapshot_json(b"WJZ1" + payload[:-1])
    ) == "SNAPSHOT_COMPRESSION_TRUNCATED"
    assert _error_code(
        lambda: codec.decompress_snapshot_json(b"WJZ1" + payload + b"junk")
    ) == "SNAPSHOT_COMPRESSION_TRAILING_DATA"


def test_snapshot_rejects_prefix_utf8_json_tree_and_hash_corruption() -> None:
    tree = make_form("program")
    canonical = codec.canonical_json(tree)
    expected_hash = codec.hash_value(tree)

    assert _error_code(
        lambda: codec.decompress_snapshot_json(b"BAD!payload")
    ) == "SNAPSHOT_ENCODING_INVALID"
    assert _error_code(
        lambda: codec.decompress_snapshot_json(b"WJR1\xff")
    ) == "SNAPSHOT_UTF8_INVALID"
    assert _error_code(
        lambda: codec.decode_snapshot_text("{", expected_hash=expected_hash)
    ) == "SNAPSHOT_JSON_INVALID"
    assert _error_code(
        lambda: codec.decode_snapshot_text(
            codec.canonical_json({"not": "a tree"}),
            expected_hash=codec.hash_value({"not": "a tree"}),
        )
    ) == "SNAPSHOT_TREE_INVALID"
    assert _error_code(
        lambda: codec.decode_snapshot_text(canonical, expected_hash="0" * 64)
    ) == "SNAPSHOT_AST_HASH_MISMATCH"


def test_revision_loader_verifies_module_and_root_hashes() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute(
        """CREATE TABLE module_snapshots_compressed (
               revision_id TEXT NOT NULL,
               qualified_name TEXT NOT NULL,
               ast_blob BLOB NOT NULL,
               ast_hash TEXT NOT NULL
           )"""
    )
    tree = make_form("program")
    canonical = codec.canonical_json(tree)
    connection.execute(
        "INSERT INTO module_snapshots_compressed VALUES (?, ?, ?, ?)",
        (
            "revision",
            "main.weave",
            codec.compress_snapshot_json(canonical),
            codec.hash_value(tree),
        ),
    )

    state = codec.load_revision_state(
        connection,
        "revision",
        expected_root_hash=codec.hash_value({"main.weave": tree}),
    )
    assert state.modules == {"main.weave": tree}
    assert state.module_count == 1
    assert state.decoded_bytes == len(canonical.encode("utf-8"))

    assert _error_code(
        lambda: codec.load_revision_state(
            connection,
            "revision",
            expected_root_hash="0" * 64,
        )
    ) == "REVISION_ROOT_HASH_MISMATCH"


def test_revision_loader_enforces_module_and_aggregate_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute(
        """CREATE TABLE module_snapshots_compressed (
               revision_id TEXT NOT NULL,
               qualified_name TEXT NOT NULL,
               ast_blob BLOB NOT NULL,
               ast_hash TEXT NOT NULL
           )"""
    )
    first = make_form("first")
    second = make_form("second")
    for name, tree in (("a.weave", first), ("b.weave", second)):
        connection.execute(
            "INSERT INTO module_snapshots_compressed VALUES (?, ?, ?, ?)",
            (
                "revision",
                name,
                codec.compress_snapshot_json(codec.canonical_json(tree)),
                codec.hash_value(tree),
            ),
        )

    monkeypatch.setattr(codec, "MAX_REVISION_MODULES", 1)
    assert _error_code(
        lambda: codec.load_revision_state(
            connection,
            "revision",
            expected_root_hash=codec.hash_value(
                {"a.weave": first, "b.weave": second}
            ),
        )
    ) == "REVISION_MODULE_LIMIT_EXCEEDED"

    monkeypatch.setattr(codec, "MAX_REVISION_MODULES", 2)
    monkeypatch.setattr(
        codec,
        "MAX_REVISION_DECODED_BYTES",
        len(codec.canonical_json(first).encode("utf-8")),
    )
    assert _error_code(
        lambda: codec.load_revision_state(
            connection,
            "revision",
            expected_root_hash=codec.hash_value(
                {"a.weave": first, "b.weave": second}
            ),
        )
    ) == "REVISION_DECODED_LIMIT_EXCEEDED"
