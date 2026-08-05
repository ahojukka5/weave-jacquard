from __future__ import annotations

import json
from pathlib import Path

from weave_frontend.compiler import validate_compiler_manifest


def _manifest(source: Path, output: Path) -> dict[str, object]:
    return {
        "format": "weavec-build-manifest-v1",
        "status": "succeeded",
        "phase": "complete",
        "target": "x86_64-unknown-linux-gnu",
        "compiler": "/opt/weavec",
        "runtime": "/opt/libweave-runtime.a",
        "codegen": "clang",
        "linker": "clang",
        "output": str(output),
        "sources": [str(source)],
    }


def _validate(tmp_path: Path, value: object, **overrides: object):
    source = tmp_path / "source.weave"
    output = tmp_path / "program"
    source.write_text("(program)\n", encoding="utf-8")
    path = tmp_path / "compiler-manifest.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    arguments = {
        "expected_sources": [source],
        "expected_output": output,
        "requested_target": None,
        "returncode": 0,
        "diagnostics_status": "succeeded",
    }
    arguments.update(overrides)
    return validate_compiler_manifest(path, **arguments)


def test_valid_manifest_is_accepted(tmp_path: Path) -> None:
    source = tmp_path / "source.weave"
    output = tmp_path / "program"
    source.write_text("(program)\n", encoding="utf-8")
    document = _manifest(source, output)

    parsed, errors = _validate(tmp_path, document)

    assert parsed == document
    assert errors == []


def test_manifest_rejects_wrong_source_order_target_and_output(tmp_path: Path) -> None:
    first = tmp_path / "first.weave"
    second = tmp_path / "second.weave"
    output = tmp_path / "program"
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")
    path = tmp_path / "compiler-manifest.json"
    value = _manifest(first, tmp_path / "other-program")
    value["sources"] = [str(second), str(first)]
    value["target"] = "wrong-target"
    path.write_text(json.dumps(value), encoding="utf-8")

    _, errors = validate_compiler_manifest(
        path,
        expected_sources=[first, second],
        expected_output=output,
        requested_target="expected-target",
        returncode=0,
        diagnostics_status="succeeded",
    )

    assert any("sources do not match" in error for error in errors)
    assert any("target does not match" in error for error in errors)
    assert any("output does not match" in error for error in errors)


def test_manifest_rejects_malformed_or_inconsistent_success(tmp_path: Path) -> None:
    path = tmp_path / "compiler-manifest.json"
    path.write_text("{not-json", encoding="utf-8")
    source = tmp_path / "source.weave"
    output = tmp_path / "program"

    parsed, errors = validate_compiler_manifest(
        path,
        expected_sources=[source],
        expected_output=output,
        requested_target=None,
        returncode=0,
        diagnostics_status="succeeded",
    )

    assert parsed is None
    assert errors and "cannot read" in errors[0]

    value = _manifest(source, output)
    value["status"] = "failed"
    value["phase"] = "backend"
    path.write_text(json.dumps(value), encoding="utf-8")
    _, errors = validate_compiler_manifest(
        path,
        expected_sources=[source],
        expected_output=output,
        requested_target=None,
        returncode=0,
        diagnostics_status="succeeded",
    )
    assert any("process return code" in error for error in errors)
    assert any("compiler diagnostics" in error for error in errors)


def test_manifest_rejects_relative_path_escape(tmp_path: Path) -> None:
    source = tmp_path / "source.weave"
    output = tmp_path / "program"
    source.write_text("(program)\n", encoding="utf-8")
    path = tmp_path / "compiler-manifest.json"
    value = _manifest(source, output)
    value["output"] = "../program"
    value["sources"] = ["../source.weave"]
    path.write_text(json.dumps(value), encoding="utf-8")

    _, errors = validate_compiler_manifest(
        path,
        expected_sources=[source],
        expected_output=output,
        requested_target=None,
        returncode=0,
        diagnostics_status="succeeded",
    )

    assert any("output must be a non-empty path" in error for error in errors)
    assert any("source 0 must be a non-empty path" in error for error in errors)
