from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from weave_frontend.compiler import CompilerBridge
from weave_frontend.errors import NotFoundError, ValidationError
from weave_frontend.sexpr_service import SExpressionWorkspace

MAIN = """(program
  (name "main")
  (version "0.1")
  (entry main
    (params)
    (returns i32)
    (do (return (const_i32 42)))))
"""
LIBRARY = """(program
  (name "library")
  (version "0.1")
  (fn helper
    (params)
    (returns i32)
    (do (return (const_i32 7)))))
"""
FAILING_LIBRARY = LIBRARY.replace("(const_i32 7)", "(unknown_form 7)")


def _fake_compiler(path: Path) -> Path:
    path.write_text(
        r"""#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def position(text: str, offset: int) -> tuple[int, int]:
    prefix = text[:offset]
    return prefix.count("\n") + 1, len(prefix.rsplit("\n", 1)[-1]) + 1


def manifest_document(
    *, status: str, phase: str, sources: list[Path], output: Path,
) -> dict[str, object]:
    return {
        "format": "weavec-build-manifest-v1",
        "status": status,
        "phase": phase,
        "target": "x86_64-unknown-linux-gnu",
        "compiler": str(Path(sys.argv[0]).resolve()),
        "runtime": "/opt/weavec/libweave-runtime.a",
        "codegen": "clang",
        "linker": "clang",
        "output": str(output),
        "sources": [str(source) for source in sources],
    }


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    if len(sys.argv) < 8 or sys.argv[1] != "build":
        return 2
    try:
        output_index = sys.argv.index("-o")
        manifest_index = sys.argv.index("--manifest-json")
        diagnostics_index = sys.argv.index("--diagnostics-json")
    except ValueError:
        return 2

    sources = [Path(value) for value in sys.argv[2:output_index]]
    output = Path(sys.argv[output_index + 1])
    manifest = Path(sys.argv[manifest_index + 1])
    diagnostics = Path(sys.argv[diagnostics_index + 1])

    for source in sources:
        text = source.read_text(encoding="utf-8")
        token = "unknown_form"
        if token not in text:
            continue
        start_character = text.index(token)
        end_character = start_character + len(token)
        start_line, start_column = position(text, start_character)
        end_line, end_column = position(text, end_character)
        write_json(
            manifest,
            manifest_document(
                status="failed", phase="backend", sources=sources, output=output
            ),
        )
        write_json(
            diagnostics,
            {
                "format": "weavec-diagnostics-v1",
                "status": "failed",
                "phase": "backend",
                "exit_code": 11,
                "raw_exit_code": 1,
                "diagnostics": [{
                    "code": "backend.unknown-expression-operator",
                    "severity": "error",
                    "phase": "backend",
                    "message": "unknown expression operator: unknown_form",
                    "source": str(source),
                    "span_origin": "inferred-unique-token",
                    "span": {
                        "start_byte": len(text[:start_character].encode("utf-8")),
                        "end_byte": len(text[:end_character].encode("utf-8")),
                        "start_line": start_line,
                        "start_column": start_column,
                        "end_line": end_line,
                        "end_column": end_column,
                    },
                }],
            },
        )
        return 11

    output.write_text("#!/bin/sh\nexit 42\n", encoding="utf-8")
    os.chmod(output, 0o755)
    write_json(
        manifest,
        manifest_document(
            status="succeeded", phase="complete", sources=sources, output=output
        ),
    )
    write_json(
        diagnostics,
        {
            "format": "weavec-diagnostics-v1",
            "status": "succeeded",
            "phase": "complete",
            "exit_code": 0,
            "raw_exit_code": 0,
            "diagnostics": [],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
""",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _workspace(tmp_path: Path, compiler: Path) -> SExpressionWorkspace:
    workspace = SExpressionWorkspace(tmp_path / "weave.db", weavec_binary=compiler)
    workspace.initialize("demo")
    workspace.import_program("demo", "main", "main.weave", MAIN)
    workspace.import_program("demo", "main", "library.weave", LIBRARY)
    return workspace


def test_multidocument_build_preserves_requested_order(tmp_path: Path) -> None:
    compiler = _fake_compiler(tmp_path / "weavec")
    with _workspace(tmp_path, compiler) as workspace:
        bridge = CompilerBridge(workspace, compiler=compiler, build_root=tmp_path / "builds")
        result = bridge.build("demo", "main.weave", additional_documents=["library.weave"])
        cached = bridge.build("demo", "main.weave", additional_documents=["library.weave"])

    assert result["status"] == "succeeded"
    assert result["compiler_manifest_protocol_valid"] is True
    assert result["documents"] == ["main.weave", "library.weave"]
    assert [item["document"] for item in result["sources"]] == result["documents"]
    assert cached["build_id"] == result["build_id"]
    assert cached["cached"] is True

    source_paths = [Path(value) for value in result["artifact_paths"]["sources"]]
    map_paths = [Path(value) for value in result["artifact_paths"]["node_maps"]]
    assert [path.name for path in source_paths] == [
        "000-main.weave",
        "001-library.weave",
    ]
    assert len(map_paths) == 2
    assert result["artifact_paths"]["source"] == str(source_paths[0])
    assert result["artifact_paths"]["node_map"] == str(map_paths[0])

    compiler_manifest = json.loads(
        Path(result["artifact_paths"]["compiler_manifest"]).read_text(encoding="utf-8")
    )
    assert compiler_manifest["sources"] == [
        "sources/000-main.weave",
        "sources/001-library.weave",
    ]
    executable = Path(result["artifact_paths"]["executable"])
    assert subprocess.run([str(executable)], check=False).returncode == 42


def test_secondary_document_diagnostic_maps_to_its_node(tmp_path: Path) -> None:
    compiler = _fake_compiler(tmp_path / "weavec")
    with _workspace(tmp_path, compiler) as workspace:
        workspace.import_program("demo", "main", "library.weave", FAILING_LIBRARY, replace=True)
        result = CompilerBridge(workspace, compiler=compiler, build_root=tmp_path / "builds").build(
            "demo", "main.weave", additional_documents=["library.weave"]
        )

    assert result["status"] == "failed"
    assert result["returncode"] == 11
    assert result["compiler_manifest_protocol_valid"] is True
    assert result["artifact_paths"]["executable"] is None
    diagnostics = json.loads(
        Path(result["artifact_paths"]["diagnostics"]).read_text(encoding="utf-8")
    )
    entry = diagnostics["entries"][0]
    assert entry["document"] == "library.weave"
    assert entry["source"] == "001-library.weave"
    assert entry["node_id"] is not None
    assert entry["message"] == "unknown expression operator: unknown_form"


def test_build_document_set_rejects_duplicates_and_missing_documents(
    tmp_path: Path,
) -> None:
    compiler = _fake_compiler(tmp_path / "weavec")
    with _workspace(tmp_path, compiler) as workspace:
        bridge = CompilerBridge(workspace, compiler=compiler, build_root=tmp_path / "builds")
        with pytest.raises(ValidationError) as duplicate:
            bridge.build("demo", "main.weave", additional_documents=["main.weave"])
        with pytest.raises(NotFoundError):
            bridge.build("demo", "main.weave", additional_documents=["missing.weave"])

    assert duplicate.value.code == "DUPLICATE_BUILD_DOCUMENT"
