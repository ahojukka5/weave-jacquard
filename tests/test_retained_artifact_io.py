from __future__ import annotations

import json
from pathlib import Path

import pytest

from weave_frontend.retained_artifact_io import (
    RetainedArtifactReadError,
    RetainedArtifactTooLarge,
    read_bounded_regular_bytes,
    read_bounded_regular_json,
)


def test_bounded_regular_read_accepts_exact_limit(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    payload = b'{"value":1}'
    path.write_bytes(payload)

    assert read_bounded_regular_bytes(path, max_bytes=len(payload)) == payload
    assert read_bounded_regular_json(path, max_bytes=len(payload)) == {"value": 1}


def test_bounded_regular_read_rejects_limit_plus_one(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_bytes(b"12345")

    with pytest.raises(RetainedArtifactTooLarge) as captured:
        read_bounded_regular_bytes(path, max_bytes=4)

    assert captured.value.limit == 4
    assert captured.value.observed >= 5


def test_bounded_regular_read_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    path = tmp_path / "manifest.json"
    path.symlink_to(target)

    with pytest.raises(RetainedArtifactReadError, match="symlink"):
        read_bounded_regular_json(path, max_bytes=64)


def test_bounded_regular_read_rejects_directory(tmp_path: Path) -> None:
    with pytest.raises(RetainedArtifactReadError, match="regular file"):
        read_bounded_regular_bytes(tmp_path, max_bytes=64)


def test_bounded_regular_read_rejects_invalid_utf8_and_json(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_bytes(b"\xff")
    with pytest.raises(RetainedArtifactReadError, match="JSON"):
        read_bounded_regular_json(path, max_bytes=64)

    path.write_text("not-json", encoding="utf-8")
    with pytest.raises(RetainedArtifactReadError, match="JSON"):
        read_bounded_regular_json(path, max_bytes=64)


def test_bounded_regular_json_preserves_json_value_shapes(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    value = {"items": [1, True, None], "name": "artifact"}
    payload = json.dumps(value).encode("utf-8")
    path.write_bytes(payload)

    assert read_bounded_regular_json(path, max_bytes=len(payload)) == value
