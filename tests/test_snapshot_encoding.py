from __future__ import annotations

import pytest

from weave_frontend.database import _compress_json, _decompress_json


def test_small_snapshot_uses_raw_versioned_payload():
    encoded = _compress_json("{}")

    assert encoded.startswith(b"WJR1")
    assert _decompress_json(encoded) == "{}"


def test_large_snapshot_uses_compressed_versioned_payload():
    value = '{"payload":"' + ("repeated-" * 1000) + '"}'
    encoded = _compress_json(value)

    assert encoded.startswith(b"WJZ1")
    assert len(encoded) < len(value.encode("utf-8")) // 4
    assert _decompress_json(encoded) == value


def test_unknown_snapshot_encoding_is_rejected():
    with pytest.raises(ValueError, match="unsupported snapshot encoding"):
        _decompress_json(b"BAD1payload")
