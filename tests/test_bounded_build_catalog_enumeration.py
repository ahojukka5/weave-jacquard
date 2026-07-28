from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import weave_frontend.verified_build_discovery as discovery_module
from weave_frontend.errors import ValidationError
from weave_frontend.mcp_build_discovery import (
    BuildDiscoveryService as ProductionBuildDiscoveryService,
)
from weave_frontend.verified_build_discovery import BuildDiscoveryService


def _service(root: Path) -> BuildDiscoveryService:
    bridge = SimpleNamespace(build_root=root)
    return BuildDiscoveryService(bridge)


def _build_directory(root: Path, build_id: str) -> None:
    directory = root / build_id
    directory.mkdir(parents=True)
    (directory / "manifest.json").write_text("{}", encoding="utf-8")


def test_production_build_discovery_uses_bounded_service() -> None:
    assert ProductionBuildDiscoveryService is BuildDiscoveryService


def test_catalog_accepts_exact_root_entry_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(discovery_module, "MAX_BUILD_CATALOG_ENTRIES", 3)
    first = "1" * 32
    second = "2" * 32
    _build_directory(tmp_path, second)
    (tmp_path / "ignored.lock").write_text("", encoding="utf-8")
    _build_directory(tmp_path, first)

    assert _service(tmp_path)._candidate_build_ids() == [first, second]


def test_catalog_rejects_limit_plus_one_even_when_entries_are_junk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(discovery_module, "MAX_BUILD_CATALOG_ENTRIES", 3)
    for index in range(4):
        (tmp_path / f"junk-{index}").write_text("", encoding="utf-8")

    with pytest.raises(ValidationError) as captured:
        _service(tmp_path)._candidate_build_ids()

    assert captured.value.code == "BUILD_CATALOG_LIMIT_EXCEEDED"
    assert "3" in captured.value.message


def test_catalog_skips_symlinked_build_directories(tmp_path: Path) -> None:
    build_id = "a" * 32
    target = tmp_path / "target"
    _build_directory(target, build_id)
    (tmp_path / build_id).symlink_to(target / build_id, target_is_directory=True)

    assert _service(tmp_path)._candidate_build_ids() == []
