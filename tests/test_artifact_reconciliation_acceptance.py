from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

import weave_frontend.artifact_reconciliation as reconciliation_module
from weave_frontend.artifact_reconciliation import (
    RetainedArtifactFamily,
    RetainedArtifactInventoryService,
)
from weave_frontend.errors import ArtifactIntegrityError, ValidationError

_HEX32 = re.compile(r"^[0-9a-f]{32}$")


def _family(root: Path, verifier: Any) -> RetainedArtifactFamily:
    return RetainedArtifactFamily(
        "committed_builds",
        root,
        _HEX32,
        verifier,
    )


def test_inventory_distinguishes_named_corruption_and_internal_examples(
    tmp_path: Path,
) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("special-file classification requires POSIX mkfifo")

    root = tmp_path / "secret-retained-root"
    root.mkdir()
    wrong_hash_id = "a" * 32
    corrupt_manifest_id = "b" * 32
    special_id = "c" * 32
    stale_stage = root / ".stale-publication-stage"
    (root / wrong_hash_id).mkdir()
    (root / corrupt_manifest_id).mkdir()
    stale_stage.mkdir()
    os.utime(stale_stage, (1, 1))
    os.mkfifo(root / special_id)

    calls: list[str] = []

    def verify(artifact_id: str) -> dict[str, str]:
        calls.append(artifact_id)
        if artifact_id == wrong_hash_id:
            raise ArtifactIntegrityError("retained artifact hash mismatch")
        if artifact_id == corrupt_manifest_id:
            raise ValidationError(
                "ARTIFACT_MANIFEST_INVALID",
                "retained artifact manifest is invalid",
            )
        return {"artifact_id": artifact_id}

    report = RetainedArtifactInventoryService([_family(root, verify)]).report()

    family = report["families"][0]
    assert family["counts"] == {
        "verified": 0,
        "corrupt": 2,
        "staging": 1,
        "quarantined": 0,
        "lock_internal": 0,
        "unknown": 1,
    }
    assert calls == [wrong_hash_id, corrupt_manifest_id]
    assert {example["error_code"] for example in family["examples"]["corrupt"]} == {
        "ARTIFACT_INTEGRITY_ERROR",
        "ARTIFACT_MANIFEST_INVALID",
    }
    assert family["examples"]["staging"][0]["entry_type"] == "directory"
    unknown = family["examples"]["unknown"][0]
    assert unknown["artifact_id"] == special_id
    assert unknown["entry_type"] == "special"
    assert unknown["classification"] == "unknown"

    encoded = json.dumps(report, sort_keys=True)
    assert str(root) not in encoded
    assert stale_stage.name not in encoded


class _ScandirContext:
    def __init__(self, entries: list[os.DirEntry[str]]) -> None:
        self.entries = entries

    def __enter__(self) -> Any:
        return iter(self.entries)

    def __exit__(self, *_args: Any) -> None:
        return None


def test_inventory_is_deterministic_across_enumeration_orders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    for name in ("unknown-c", "unknown-a", "unknown-b"):
        (root / name).mkdir()

    real_scandir = reconciliation_module.os.scandir
    calls = 0

    def alternating_scandir(path: Path) -> _ScandirContext:
        nonlocal calls
        with real_scandir(path) as iterator:
            entries = list(iterator)
        calls += 1
        if calls % 2 == 0:
            entries.reverse()
        return _ScandirContext(entries)

    monkeypatch.setattr(
        reconciliation_module.os,
        "scandir",
        alternating_scandir,
    )
    service = RetainedArtifactInventoryService([_family(root, lambda _artifact_id: {})])

    first = service.report()
    second = service.report()

    assert calls == 4
    assert first == second
    assert first["families"][0]["counts"]["unknown"] == 3
