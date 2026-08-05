from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import pytest

from weave_frontend.compiler import BUILD_KEY_FORMAT, MAX_COMPILER_OUTPUT_BYTES, CompilerBridge
from weave_frontend.errors import ValidationError


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: dict[str, object]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _write_build(
    directory: Path,
    *,
    succeeded: bool,
    payload: str = "program",
    build_id: str | None = None,
) -> str:
    directory.mkdir(exist_ok=True)
    source_text = "(program)\n"
    (directory / "source.weave").write_text(source_text, encoding="utf-8")
    (directory / "source.map.json").write_text("{}\n", encoding="utf-8")
    diagnostics = {
        "format": "weave-build-diagnostics-v1",
        "returncode": 0 if succeeded else 11,
        "timed_out": False,
        "output_limited": False,
        "compiler_output_limit_bytes": MAX_COMPILER_OUTPUT_BYTES,
        "protocol_valid": True,
        "protocol_errors": [],
        "entries": [],
    }
    (directory / "diagnostics.json").write_text(json.dumps(diagnostics) + "\n", encoding="utf-8")
    (directory / "compiler-manifest.json").write_text("{}\n", encoding="utf-8")
    (directory / "compiler-diagnostics.json").write_text("{}\n", encoding="utf-8")
    if succeeded:
        (directory / "program").write_text(payload, encoding="utf-8")
    source_sha256 = hashlib.sha256(source_text.encode()).hexdigest()
    revision_hash = "a" * 64
    revision_id = "revision-1"
    compiler_sha256 = "b" * 64
    target = "native"
    documents = ["main.weave"]
    sources = [
        {
            "document": "main.weave",
            "source": "source.weave",
            "node_map": "source.map.json",
            "source_sha256": source_sha256,
        }
    ]
    cache_payload = {
        "format": BUILD_KEY_FORMAT,
        "revision_hash": revision_hash,
        "revision_id": revision_id,
        "documents": [{"document": "main.weave", "source_sha256": source_sha256}],
        "compiler_sha256": compiler_sha256,
        "compiler_output_limit_bytes": MAX_COMPILER_OUTPUT_BYTES,
        "target": target,
    }
    computed_build_id = hashlib.sha256(_canonical(cache_payload)).hexdigest()[:32]
    resolved_build_id = build_id if build_id is not None else computed_build_id
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
        "build_id": resolved_build_id,
        "status": "succeeded" if succeeded else "failed",
        "returncode": 0 if succeeded else 11,
        "timed_out": False,
        "output_limited": False,
        "compiler_output_limit_bytes": MAX_COMPILER_OUTPUT_BYTES,
        "revision_id": revision_id,
        "revision_hash": revision_hash,
        "documents": documents,
        "document": documents[0],
        "sources": sources,
        "source_sha256": source_sha256,
        "compiler_sha256": compiler_sha256,
        "target": target,
        "compiler_diagnostics_protocol_valid": True,
        "compiler_manifest_protocol_valid": True,
        "artifacts": artifacts,
        "artifact_sha256": {relative: _sha(directory / relative) for relative in references},
    }
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return resolved_build_id


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

    assert CompilerBridge._read_successful_manifest(build, expected_build_id=build.name) is None

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
    build_root.mkdir()
    staging = tmp_path / "staging"
    build_id = _write_build(staging, succeeded=True)
    build = build_root / build_id
    staging.rename(build)

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
    successful = tmp_path / "successful"
    failed = tmp_path / "failed"
    build_id = _write_build(successful, succeeded=True, payload="good")
    _write_build(failed, succeeded=False)
    final = tmp_path / build_id
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
    first = tmp_path / "first"
    second = tmp_path / "second"
    build_id = _write_build(first, succeeded=True, payload="first")
    _write_build(second, succeeded=True, payload="second")
    final = tmp_path / build_id
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
    successful = tmp_path / "successful-replacement"
    failed = tmp_path / "failed-existing"
    build_id = _write_build(failed, succeeded=False)
    final = tmp_path / build_id
    failed.rename(final)
    _write_build(
        succeeded=True,
        directory=successful,
        payload="replacement",
    )

    CompilerBridge._publish_directory(successful, final)

    assert CompilerBridge._read_successful_manifest(final) is not None
    assert (final / "program").read_text(encoding="utf-8") == "replacement"
    assert not successful.exists()
    assert not list(tmp_path.glob(".*.replaced-*"))


def test_incomplete_temporary_build_never_replaces_existing_build(tmp_path: Path) -> None:
    incomplete = tmp_path / "incomplete"
    existing = tmp_path / "existing"
    build_id = _write_build(existing, succeeded=False)
    final = tmp_path / build_id
    existing.rename(final)
    _write_build(incomplete, succeeded=True)
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
    build_root.mkdir()
    staging = tmp_path / "staging"
    build_id = _write_build(staging, succeeded=True)
    build = build_root / build_id
    staging.rename(build)
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
