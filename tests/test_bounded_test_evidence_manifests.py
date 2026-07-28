from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pytest

from weave_frontend.errors import ArtifactIntegrityError
from weave_frontend.test_batches import (
    MAX_TEST_BATCH_MANIFEST_BYTES,
    TestBatchService,
)
from weave_frontend.test_runs import MAX_TEST_RUN_MANIFEST_BYTES, TestRunService


Reader = Callable[[Path], dict[str, object]]


def _json_object_with_size(size: int) -> bytes:
    base = {"padding": ""}
    encoded = json.dumps(base, separators=(",", ":")).encode("utf-8")
    padding = size - len(encoded)
    assert padding >= 0
    base["padding"] = "x" * padding
    result = json.dumps(base, separators=(",", ":")).encode("utf-8")
    assert len(result) == size
    return result


@pytest.mark.parametrize(
    ("reader", "limit"),
    [
        (TestRunService._read_json, MAX_TEST_RUN_MANIFEST_BYTES),
        (TestBatchService._read_json, MAX_TEST_BATCH_MANIFEST_BYTES),
    ],
)
def test_test_evidence_manifest_accepts_exact_limit(
    tmp_path: Path,
    reader: Reader,
    limit: int,
) -> None:
    path = tmp_path / "manifest.json"
    path.write_bytes(_json_object_with_size(limit))

    assert reader(path)["padding"] == "x" * (limit - len('{"padding":""}'))


@pytest.mark.parametrize(
    ("reader", "limit"),
    [
        (TestRunService._read_json, MAX_TEST_RUN_MANIFEST_BYTES),
        (TestBatchService._read_json, MAX_TEST_BATCH_MANIFEST_BYTES),
    ],
)
def test_test_evidence_manifest_rejects_limit_plus_one(
    tmp_path: Path,
    reader: Reader,
    limit: int,
) -> None:
    path = tmp_path / "manifest.json"
    path.write_bytes(_json_object_with_size(limit + 1))

    with pytest.raises(ArtifactIntegrityError, match="exceeds"):
        reader(path)


@pytest.mark.parametrize(
    "reader",
    [TestRunService._read_json, TestBatchService._read_json],
)
def test_test_evidence_manifest_rejects_symlink(
    tmp_path: Path,
    reader: Reader,
) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    path = tmp_path / "manifest.json"
    path.symlink_to(target)

    with pytest.raises(ArtifactIntegrityError, match="symlink"):
        reader(path)


@pytest.mark.parametrize(
    "reader",
    [TestRunService._read_json, TestBatchService._read_json],
)
def test_test_evidence_manifest_rejects_non_regular_file(
    tmp_path: Path,
    reader: Reader,
) -> None:
    path = tmp_path / "manifest.json"
    path.mkdir()

    with pytest.raises(ArtifactIntegrityError, match="regular file"):
        reader(path)
