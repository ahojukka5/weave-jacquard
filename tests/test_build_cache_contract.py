from __future__ import annotations

import hashlib
import json
from pathlib import Path

from weave_frontend.compiler_bridge import BUILD_KEY_FORMAT, CompilerBridge
from weave_frontend.compiler_limits import MAX_COMPILER_OUTPUT_BYTES


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: dict[str, object]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _write_cached_build(
    directory: Path,
    *,
    build_key_format: str,
    diagnostics_valid: bool = True,
    manifest_valid: bool = True,
    include_compiler_diagnostics: bool = True,
    include_compiler_manifest: bool = True,
    include_sources: bool = True,
) -> None:
    directory.mkdir()
    (directory / "program").write_text("executable", encoding="utf-8")
    diagnostics = {
        "format": "weave-build-diagnostics-v1",
        "returncode": 0,
        "timed_out": False,
        "output_limited": False,
        "compiler_output_limit_bytes": MAX_COMPILER_OUTPUT_BYTES,
        "protocol_valid": diagnostics_valid,
        "protocol_errors": [],
        "entries": [],
    }
    (directory / "diagnostics.json").write_text(
        json.dumps(diagnostics) + "\n", encoding="utf-8"
    )
    artifacts: dict[str, object] = {
        "source": "sources/000-main.weave" if include_sources else None,
        "node_map": (
            "source-maps/000-main.weave.map.json" if include_sources else None
        ),
        "sources": ["sources/000-main.weave"] if include_sources else [],
        "node_maps": (
            ["source-maps/000-main.weave.map.json"] if include_sources else []
        ),
        "diagnostics": "diagnostics.json",
        "compiler_manifest": (
            "compiler-manifest.json" if include_compiler_manifest else None
        ),
        "compiler_diagnostics": (
            "compiler-diagnostics.json" if include_compiler_diagnostics else None
        ),
        "executable": "program",
    }
    if include_compiler_manifest:
        (directory / "compiler-manifest.json").write_text(
            '{"format":"weavec-build-manifest-v1"}\n', encoding="utf-8"
        )
    if include_compiler_diagnostics:
        (directory / "compiler-diagnostics.json").write_text(
            '{"format":"weavec-diagnostics-v1"}\n', encoding="utf-8"
        )
    source_sha256 = None
    sources_meta: list[dict[str, str]] = []
    if include_sources:
        (directory / "sources").mkdir()
        (directory / "source-maps").mkdir()
        source_text = "(program)\n"
        (directory / "sources/000-main.weave").write_text(
            source_text, encoding="utf-8"
        )
        (directory / "source-maps/000-main.weave.map.json").write_text(
            '{"format":"weave-node-map-v1"}\n', encoding="utf-8"
        )
        source_sha256 = hashlib.sha256(source_text.encode()).hexdigest()
        sources_meta = [
            {
                "document": "main.weave",
                "source": "sources/000-main.weave",
                "node_map": "source-maps/000-main.weave.map.json",
                "source_sha256": source_sha256,
            }
        ]

    references = set(CompilerBridge._artifact_references(artifacts))
    revision_hash = "a" * 64
    revision_id = "revision-1"
    compiler_sha256 = "b" * 64
    target = "native"
    cache_payload = {
        "format": build_key_format,
        "revision_hash": revision_hash,
        "revision_id": revision_id,
        "documents": (
            [{"document": "main.weave", "source_sha256": source_sha256}]
            if source_sha256 is not None
            else []
        ),
        "compiler_sha256": compiler_sha256,
        "compiler_output_limit_bytes": MAX_COMPILER_OUTPUT_BYTES,
        "target": target,
    }
    build_id = hashlib.sha256(_canonical(cache_payload)).hexdigest()[:32]
    manifest = {
        "format": "weave-frontend-build-manifest-v2",
        "build_key_format": build_key_format,
        "build_id": build_id,
        "status": "succeeded",
        "returncode": 0,
        "timed_out": False,
        "output_limited": False,
        "compiler_output_limit_bytes": MAX_COMPILER_OUTPUT_BYTES,
        "revision_id": revision_id,
        "revision_hash": revision_hash,
        "documents": ["main.weave"] if include_sources else [],
        "document": "main.weave" if include_sources else None,
        "sources": sources_meta,
        "source_sha256": source_sha256,
        "compiler_sha256": compiler_sha256,
        "target": target,
        "compiler_diagnostics_protocol_valid": diagnostics_valid,
        "compiler_manifest_protocol_valid": manifest_valid,
        "artifacts": artifacts,
        "artifact_sha256": {
            relative: _sha(directory / relative) for relative in references
        },
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest) + "\n", encoding="utf-8"
    )


def test_cache_rejects_previous_build_key_contract(tmp_path: Path) -> None:
    cached = tmp_path / "cached"
    _write_cached_build(cached, build_key_format="weave-build-key-v3")

    assert CompilerBridge._read_successful_manifest(cached) is None


def test_cache_requires_both_compiler_protocol_artifacts(tmp_path: Path) -> None:
    invalid_diagnostics = tmp_path / "invalid-diagnostics"
    _write_cached_build(
        invalid_diagnostics,
        build_key_format=BUILD_KEY_FORMAT,
        diagnostics_valid=False,
    )
    invalid_manifest = tmp_path / "invalid-manifest"
    _write_cached_build(
        invalid_manifest,
        build_key_format=BUILD_KEY_FORMAT,
        manifest_valid=False,
    )
    missing_diagnostics = tmp_path / "missing-diagnostics"
    _write_cached_build(
        missing_diagnostics,
        build_key_format=BUILD_KEY_FORMAT,
        include_compiler_diagnostics=False,
    )
    missing_manifest = tmp_path / "missing-manifest"
    _write_cached_build(
        missing_manifest,
        build_key_format=BUILD_KEY_FORMAT,
        include_compiler_manifest=False,
    )
    missing_sources = tmp_path / "missing-sources"
    _write_cached_build(
        missing_sources,
        build_key_format=BUILD_KEY_FORMAT,
        include_sources=False,
    )

    assert CompilerBridge._read_successful_manifest(invalid_diagnostics) is None
    assert CompilerBridge._read_successful_manifest(invalid_manifest) is None
    assert CompilerBridge._read_successful_manifest(missing_diagnostics) is None
    assert CompilerBridge._read_successful_manifest(missing_manifest) is None
    assert CompilerBridge._read_successful_manifest(missing_sources) is None


def test_cache_accepts_current_verified_contract(tmp_path: Path) -> None:
    cached = tmp_path / "cached"
    _write_cached_build(cached, build_key_format=BUILD_KEY_FORMAT)

    manifest = CompilerBridge._read_successful_manifest(cached)

    assert manifest is not None
    assert manifest["build_key_format"] == BUILD_KEY_FORMAT
    assert manifest["artifact_paths"]["compiler_manifest"].endswith(
        "compiler-manifest.json"
    )
    assert manifest["artifact_paths"]["compiler_diagnostics"].endswith(
        "compiler-diagnostics.json"
    )
    assert manifest["artifact_paths"]["sources"][0].endswith("000-main.weave")
