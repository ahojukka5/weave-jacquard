from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

import weave_frontend.compiler_bridge as bridge_module
import weave_frontend.compiler_inputs as input_module
from weave_frontend.compiler_bridge import CompilerBridge


class _Row(dict[str, str]):
    pass


class _Cursor:
    def fetchone(self) -> _Row:
        return _Row(root_hash="root-hash")


class _Connection:
    def execute(self, *_: Any) -> _Cursor:
        return _Cursor()


class _DB:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.connection = _Connection()


class _Workspace:
    def __init__(self, path: Path) -> None:
        self.db = _DB(path)

    def branch_head(self, project: str, branch: str) -> str:
        assert project == "demo"
        assert branch == "main"
        return "revision-1"

    def _state_at_revision(self, revision: str) -> dict[str, str]:
        assert revision == "revision-1"
        return {
            "main.weave": "(program main)\n",
            "library.weave": "(program library)\n",
        }


def _render(root: str, *, revision_id: str, document: str):
    source_hash = hashlib.sha256(root.encode()).hexdigest()
    return root, {
        "format": "weave-node-map-v1",
        "source_sha256": source_hash,
        "revision_id": revision_id,
        "document": document,
        "nodes": [],
    }


def _collect(path: Path, **kwargs: Any):
    document = json.loads(path.read_text(encoding="utf-8"))
    return {
        "format": "weave-build-diagnostics-v1",
        "returncode": kwargs["returncode"],
        "timed_out": kwargs["timed_out"],
        "stdout": kwargs["stdout"],
        "stderr": kwargs["stderr"],
        "compiler": {
            "format": document["format"],
            "status": document["status"],
            "phase": document["phase"],
            "exit_code": document["exit_code"],
            "raw_exit_code": document["raw_exit_code"],
        },
        "protocol_valid": True,
        "protocol_errors": [],
        "entries": [],
    }, True


def _fake_compiler(path: Path, mode: str, counter: Path) -> Path:
    path.write_text(
        f'''#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

MODE = {mode!r}
COUNTER = Path({str(counter)!r})


def main() -> int:
    count = int(COUNTER.read_text() if COUNTER.exists() else "0")
    COUNTER.write_text(str(count + 1))
    output_index = sys.argv.index("-o")
    manifest_index = sys.argv.index("--manifest-json")
    diagnostics_index = sys.argv.index("--diagnostics-json")
    sources = [Path(value).resolve() for value in sys.argv[2:output_index]]
    output = Path(sys.argv[output_index + 1]).resolve()
    manifest = Path(sys.argv[manifest_index + 1])
    diagnostics = Path(sys.argv[diagnostics_index + 1])
    target = (
        sys.argv[sys.argv.index("--target") + 1]
        if "--target" in sys.argv
        else "x86_64-unknown-linux-gnu"
    )

    output.write_text("#!/bin/sh\\nexit 42\\n", encoding="utf-8")
    os.chmod(output, 0o755)
    diagnostics.write_text(
        json.dumps({{
            "format": "weavec-diagnostics-v1",
            "status": "succeeded",
            "phase": "complete",
            "exit_code": 0,
            "raw_exit_code": 0,
            "diagnostics": [],
        }}),
        encoding="utf-8",
    )

    if MODE == "missing":
        return 0
    if MODE == "malformed":
        manifest.write_text("{{not-json", encoding="utf-8")
        return 0

    manifest_sources = list(sources)
    manifest_target = target
    manifest_output = output
    if MODE == "wrong-source-order":
        manifest_sources.reverse()
    elif MODE == "wrong-target":
        manifest_target = "wrong-target"
    elif MODE == "wrong-output":
        manifest_output = output.with_name("other-program")

    manifest.write_text(
        json.dumps({{
            "format": "weavec-build-manifest-v1",
            "status": "succeeded",
            "phase": "complete",
            "target": manifest_target,
            "compiler": str(Path(sys.argv[0]).resolve()),
            "runtime": "/opt/weavec/libweave-runtime.a",
            "codegen": "clang",
            "linker": "clang",
            "output": str(manifest_output),
            "sources": [str(source) for source in manifest_sources],
        }}),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''',
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _bridge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str):
    counter = tmp_path / "counter"
    compiler = _fake_compiler(tmp_path / "weavec", mode, counter)
    monkeypatch.setattr(input_module, "render_with_node_map", _render)
    monkeypatch.setattr(bridge_module, "collect_build_diagnostics", _collect)
    workspace = _Workspace(tmp_path / "weave.db")
    bridge = CompilerBridge(
        workspace,
        compiler=compiler,
        build_root=tmp_path / "builds",
    )
    return bridge, counter


def test_valid_manifest_allows_success_and_cache_reuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge, counter = _bridge(tmp_path, monkeypatch, "valid")

    first = bridge.build("demo", "main.weave")
    second = bridge.build("demo", "main.weave")

    assert first["status"] == "succeeded"
    assert first["compiler_manifest_protocol_valid"] is True
    assert first["compiler_target"] == "x86_64-unknown-linux-gnu"
    assert second["cached"] is True
    assert counter.read_text() == "1"


@pytest.mark.parametrize(
    ("mode", "additional_documents", "target", "message"),
    [
        ("malformed", None, None, "cannot read compiler build manifest"),
        ("missing", None, None, "did not write a build manifest"),
        (
            "wrong-source-order",
            ["library.weave"],
            None,
            "sources do not match ordered compiler inputs",
        ),
        ("wrong-target", None, "expected-target", "target does not match"),
        ("wrong-output", None, None, "output does not match"),
    ],
)
def test_invalid_manifest_withholds_executable_and_preserves_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    additional_documents: list[str] | None,
    target: str | None,
    message: str,
) -> None:
    bridge, _ = _bridge(tmp_path, monkeypatch, mode)

    result = bridge.build(
        "demo",
        "main.weave",
        additional_documents=additional_documents,
        target=target,
    )

    assert result["status"] == "failed"
    assert result["compiler_diagnostics_protocol_valid"] is True
    assert result["compiler_manifest_protocol_valid"] is False
    assert result["artifact_paths"]["executable"] is None
    assert any(message in error for error in result["compiler_manifest_errors"])
    diagnostics = json.loads(
        Path(result["artifact_paths"]["diagnostics"]).read_text(encoding="utf-8")
    )
    assert diagnostics["entries"][-1]["code"] == "bridge.invalid-compiler-manifest"
    if mode != "missing":
        raw_manifest = Path(result["artifact_paths"]["compiler_manifest"])
        assert raw_manifest.is_file()
        if mode == "malformed":
            assert raw_manifest.read_text(encoding="utf-8") == "{not-json"
