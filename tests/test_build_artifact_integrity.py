from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import pytest

from weave_frontend.compiler_bridge import BUILD_KEY_FORMAT, CompilerBridge
from weave_frontend.errors import ValidationError


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_build(
    directory: Path,
    *,
    succeeded: bool,
    payload: str = "program",
    build_id: str = "a" * 32,
) -> None:
    directory.mkdir()
    (directory / "source.weave").write_text("(program)\n", encoding="utf-8")
    (directory / "source.map.json").write_text("{}\n", encoding="utf-8")
    (directory / "diagnostics.json").write_text("{}\n", encoding="utf-8")
    (directory / "compiler-manifest.json").write_text("{}\n", encoding="utf-8")
    (directory / "compiler-diagnostics.json").write_text("{}\n", encoding="utf-8")
    if succeeded:
        (directory / "program").write_text(payload, encoding="utf-8")
    artifacts = {
        "source": "source.weave",
        "node_map": "source.map.json",
        "sources": ["source.weave"],
        "node_maps": ["source.map.json"],
        "diagnostics": "diagnostics.json",
        "compiler_manifest": "compiler-manifest.json",
        "compiler_diagnostics": "compiler-diagnostics.json",
        "executable": "program" if succeeded else None,
    }
    references = {value for value in artifacts.values() if isinstance(value, str)}
    references.update(artifacts["sources"])
    references.update(artifacts["node_maps"])
    manifest = {
        "format": "weave-frontend-build-manifest-v2",
        "build_key_format": BUILD_KEY_FORMAT,
        "build_id": build_id,
        "status": "succeeded" if succeeded else "failed",
        "returncode": 0 if succeeded else 11,
        "compiler_diagnostics_protocol_valid": True,
        "compiler_manifest_protocol_valid": True,
        "artifacts": artifacts,
        "artifact_sha256": {
            relative: _sha(directory / relative) for relative in references
        },
    }
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


@pytest.mark.parametrize(
    "relative",
    [
        "program",
        "source.weave",
        "source.map.json",
        "diagnostics.json",
        "compiler-manifest.json",
        "compiler-diagnostics.json",
    ],
)
def test_cache_rejects_each_corrupted_artifact(
    tmp_path: Path,
    relative: str,
) -> None:
    build = tmp_path / ("a" * 32)
    _write_build(build, succeeded=True)
    assert CompilerBridge._read_successful_manifest(build) is not None

    (build / relative).write_text("corrupted", encoding="utf-8")

    assert CompilerBridge._read_successful_manifest(build) is None


@pytest.mark.parametrize(
    "invalid_hash",
    [None, "0" * 63, "A" * 64, "g" * 64, "0" * 64],
)
def test_cache_rejects_missing_malformed_or_wrong_hashes(
    tmp_path: Path,
    invalid_hash: str | None,
) -> None:
    build = tmp_path / ("a" * 32)
    _write_build(build, succeeded=True)
    manifest_path = build / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if invalid_hash is None:
        del manifest["artifact_sha256"]["program"]
    else:
        manifest["artifact_sha256"]["program"] = invalid_hash
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert CompilerBridge._read_successful_manifest(build) is None



def test_cache_binds_manifest_id_to_final_directory(tmp_path: Path) -> None:
    build = tmp_path / ("e" * 32)
    _write_build(build, succeeded=True, build_id="f" * 32)

    assert CompilerBridge._read_successful_manifest(
        build, expected_build_id=build.name
    ) is None

    class _DB:
        path = tmp_path / "weave.db"

    class _Workspace:
        db = _DB()

    bridge = CompilerBridge(_Workspace(), build_root=tmp_path)
    with pytest.raises(ValidationError) as mismatch:
        bridge.get(build.name)
    assert mismatch.value.code == "INVALID_BUILD_MANIFEST"

def test_public_get_rejects_escape_and_checksum_mismatch(tmp_path: Path) -> None:
    build_root = tmp_path / "builds"
    build_id = "a" * 32
    build = build_root / build_id
    build_root.mkdir()
    _write_build(build, succeeded=True)

    class _DB:
        path = tmp_path / "weave.db"

    class _Workspace:
        db = _DB()

    bridge = CompilerBridge(_Workspace(), build_root=build_root)
    manifest_path = build / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"]["executable"] = "../outside"
    manifest["artifact_sha256"]["../outside"] = "0" * 64
    del manifest["artifact_sha256"]["program"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValidationError) as escaped:
        bridge.get(build_id)
    assert escaped.value.code == "INVALID_ARTIFACT_PATH"

    _write_build(tmp_path / "fresh", succeeded=True)
    fresh = json.loads((tmp_path / "fresh/manifest.json").read_text(encoding="utf-8"))
    fresh["build_id"] = build_id
    for item in build.iterdir():
        if item.is_file():
            item.unlink()
    for item in (tmp_path / "fresh").iterdir():
        item.replace(build / item.name)
    (build / "program").write_text("changed", encoding="utf-8")

    with pytest.raises(ValidationError) as corrupt:
        bridge.get(build_id)
    assert corrupt.value.code == "CORRUPT_BUILD_ARTIFACT"


def test_successful_publication_wins_over_failed_race(tmp_path: Path) -> None:
    final = tmp_path / ("a" * 32)
    successful = tmp_path / "successful"
    failed = tmp_path / "failed"
    _write_build(successful, succeeded=True, payload="good")
    _write_build(failed, succeeded=False)
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def publish(path: Path) -> None:
        try:
            barrier.wait()
            CompilerBridge._publish_directory(path, final)
        except BaseException as exc:  # pragma: no cover - diagnostic capture
            errors.append(exc)

    threads = [
        threading.Thread(target=publish, args=(successful,)),
        threading.Thread(target=publish, args=(failed,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert json.loads((final / "manifest.json").read_text())["status"] == "succeeded"
    assert (final / "program").read_text(encoding="utf-8") == "good"
    assert not successful.exists()
    assert not failed.exists()
    assert not list(tmp_path.glob(".*.replaced-*"))


def test_two_successful_publishers_converge_on_first_valid_build(tmp_path: Path) -> None:
    final = tmp_path / ("b" * 32)
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_build(first, succeeded=True, payload="first", build_id=final.name)
    _write_build(second, succeeded=True, payload="second", build_id=final.name)
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def publish(path: Path) -> None:
        try:
            barrier.wait()
            CompilerBridge._publish_directory(path, final)
        except BaseException as exc:  # pragma: no cover - diagnostic capture
            errors.append(exc)

    threads = [
        threading.Thread(target=publish, args=(first,)),
        threading.Thread(target=publish, args=(second,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert CompilerBridge._read_successful_manifest(final) is not None
    assert (final / "program").read_text(encoding="utf-8") in {"first", "second"}
    assert not first.exists()
    assert not second.exists()
    assert not list(tmp_path.glob(".*.replaced-*"))


def test_success_replaces_preexisting_failed_build(tmp_path: Path) -> None:
    final = tmp_path / ("c" * 32)
    successful = tmp_path / "successful-replacement"
    _write_build(final, succeeded=False, build_id=final.name)
    _write_build(
        succeeded=True, directory=successful, payload="replacement", build_id=final.name
    )

    CompilerBridge._publish_directory(successful, final)

    assert CompilerBridge._read_successful_manifest(final) is not None
    assert (final / "program").read_text(encoding="utf-8") == "replacement"
    assert not successful.exists()
    assert not list(tmp_path.glob(".*.replaced-*"))


def test_incomplete_temporary_build_never_replaces_existing_build(tmp_path: Path) -> None:
    final = tmp_path / ("d" * 32)
    incomplete = tmp_path / "incomplete"
    _write_build(final, succeeded=False, build_id=final.name)
    _write_build(incomplete, succeeded=True, build_id=final.name)
    (incomplete / "program").unlink()

    with pytest.raises(ValidationError) as invalid:
        CompilerBridge._publish_directory(incomplete, final)

    assert invalid.value.code == "CORRUPT_BUILD_ARTIFACT"
    assert json.loads((final / "manifest.json").read_text())["status"] == "failed"
    assert incomplete.exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "unknown"),
        ("build_key_format", ""),
        ("returncode", True),
        ("compiler_diagnostics_protocol_valid", "yes"),
        ("compiler_manifest_protocol_valid", None),
    ],
)
def test_public_get_rejects_malformed_frontend_manifest_fields(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    build_root = tmp_path / "builds"
    build_id = "a" * 32
    build = build_root / build_id
    build_root.mkdir()
    _write_build(build, succeeded=True)
    manifest_path = build / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[field] = value
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    class _DB:
        path = tmp_path / "weave.db"

    class _Workspace:
        db = _DB()

    bridge = CompilerBridge(_Workspace(), build_root=build_root)
    with pytest.raises(ValidationError) as malformed:
        bridge.get(build_id)
    assert malformed.value.code == "INVALID_BUILD_MANIFEST"
