from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from weave_frontend.bounded_process import run_bounded_process
from weave_frontend.compiler import (
    CompilerBridge,
    CompilerFileTooLarge,
    WeavecValidator,
    collect_build_diagnostics,
    read_bounded_bytes,
    read_bounded_json,
    read_bounded_text,
    validate_compiler_manifest,
)


def _script(tmp_path: Path, body: str, name: str = "helper.py") -> Path:
    path = tmp_path / name
    path.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_bounded_process_accepts_exact_combined_output(tmp_path: Path) -> None:
    script = _script(
        tmp_path,
        "import sys\n"
        "sys.stdout.buffer.write(b'a' * 8)\n"
        "sys.stdout.flush()\n"
        "sys.stderr.buffer.write(b'b' * 8)\n",
    )

    result = run_bounded_process(
        [script],
        timeout_seconds=2,
        max_output_bytes=16,
    )

    assert result.returncode == 0
    assert result.timed_out is False
    assert result.output_limited is False
    assert len(result.stdout.encode()) + len(result.stderr.encode()) == 16
    assert tuple(result) == (0, False, result.stdout, result.stderr)


def test_bounded_process_kills_on_combined_output_limit(tmp_path: Path) -> None:
    script = _script(
        tmp_path,
        "import sys, time\n"
        "sys.stdout.buffer.write(b'a' * 20)\n"
        "sys.stdout.flush()\n"
        "sys.stderr.buffer.write(b'b' * 20)\n"
        "sys.stderr.flush()\n"
        "time.sleep(10)\n",
    )

    result = run_bounded_process(
        [script],
        timeout_seconds=2,
        max_output_bytes=32,
    )

    assert result.timed_out is False
    assert result.output_limited is True
    assert len(result.stdout.encode()) + len(result.stderr.encode()) == 32


def test_bounded_process_kills_on_timeout(tmp_path: Path) -> None:
    script = _script(tmp_path, "import time\ntime.sleep(10)\n")

    result = run_bounded_process(
        [script],
        timeout_seconds=0.05,
        max_output_bytes=32,
    )

    assert result.timed_out is True
    assert result.output_limited is False


def test_bounded_process_times_out_after_output_streams_close(tmp_path: Path) -> None:
    script = _script(
        tmp_path,
        "import os, time\nos.close(1)\nos.close(2)\ntime.sleep(10)\n",
        "closed-output.py",
    )

    started = time.monotonic()
    result = run_bounded_process(
        [script],
        timeout_seconds=0.05,
        max_output_bytes=32,
    )

    assert result.timed_out is True
    assert result.output_limited is False
    assert time.monotonic() - started < 2


def test_bounded_file_readers_reject_one_extra_byte(tmp_path: Path) -> None:
    text = tmp_path / "text.txt"
    text.write_bytes(b"12345")
    with pytest.raises(CompilerFileTooLarge) as raised:
        read_bounded_bytes(text, max_bytes=4)
    assert raised.value.limit == 4
    assert raised.value.observed == 5

    text.write_text("four", encoding="utf-8")
    assert read_bounded_text(text, max_bytes=4) == "four"

    document = tmp_path / "document.json"
    document.write_text('{"ok":true}', encoding="utf-8")
    assert read_bounded_json(document, max_bytes=11) == {"ok": True}


def test_frontend_validation_rejects_compiler_output_limit(tmp_path: Path) -> None:
    compiler = _script(
        tmp_path,
        "import sys, time\n"
        "sys.stdout.buffer.write(b'x' * 64)\n"
        "sys.stdout.flush()\n"
        "time.sleep(10)\n",
        "output-compiler.py",
    )
    validator = WeavecValidator(
        binary=compiler,
        timeout_seconds=2,
        max_output_bytes=32,
        max_wir_bytes=128,
    )

    result = validator.validate("(program)")

    assert result["available"] is True
    assert result["valid"] is False
    assert result["returncode"] is None
    assert result["timed_out"] is False
    assert result["output_limited"] is True
    assert result["compiler_output_limit_bytes"] == 32
    assert len(result["stdout"].encode()) + len(result["stderr"].encode()) == 32


def test_frontend_validation_rejects_oversized_wir(tmp_path: Path) -> None:
    compiler = _script(
        tmp_path,
        "import pathlib, sys\npathlib.Path(sys.argv[2]).write_bytes(b'w' * 33)\n",
        "wir-compiler.py",
    )
    validator = WeavecValidator(
        binary=compiler,
        max_output_bytes=128,
        max_wir_bytes=32,
    )

    result = validator.validate("(program)")

    assert result["available"] is True
    assert result["valid"] is False
    assert result["returncode"] == 0
    assert result["wir"] is None
    assert result["wir_too_large"] is True
    assert result["wir_limit_bytes"] == 32
    assert "exceeds 32 bytes" in result["diagnostic"]


def test_frontend_validation_reads_bounded_wir_success(tmp_path: Path) -> None:
    compiler = _script(
        tmp_path,
        "import pathlib, sys\npathlib.Path(sys.argv[2]).write_text('(wir)', encoding='utf-8')\n",
        "success-compiler.py",
    )
    validator = WeavecValidator(
        binary=compiler,
        max_output_bytes=128,
        max_wir_bytes=32,
    )

    result = validator.validate("(program)")

    assert result["valid"] is True
    assert result["wir"] == "(wir)"
    assert result["output_limited"] is False
    assert result["wir_too_large"] is False


def test_oversized_diagnostics_become_output_safe_bridge_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import weave_frontend.compiler.diagnostics as module

    source = tmp_path / "main.weave"
    source.write_text("(program)\n", encoding="utf-8")
    diagnostics = tmp_path / "compiler-diagnostics.json"
    diagnostics.write_bytes(b"x" * 17)
    monkeypatch.setattr(module, "MAX_COMPILER_PROTOCOL_BYTES", 16)

    result, valid = collect_build_diagnostics(
        diagnostics,
        returncode=1,
        timed_out=False,
        stdout="",
        stderr="",
        node_map={"document": "main.weave", "nodes": []},
        canonical_source_path=source,
    )

    assert valid is False
    assert result["compiler_protocol_limit_bytes"] == 16
    assert result["entries"][0]["code"] == "bridge.invalid-compiler-diagnostics"
    assert any("exceeds 16 bytes" in error for error in result["protocol_errors"])


def test_output_limited_diagnostics_are_never_valid(tmp_path: Path) -> None:
    source = tmp_path / "main.weave"
    source.write_text("(program)\n", encoding="utf-8")
    diagnostics = tmp_path / "compiler-diagnostics.json"
    diagnostics.write_text(
        json.dumps(
            {
                "format": "weavec-diagnostics-v1",
                "status": "succeeded",
                "phase": "complete",
                "exit_code": 0,
                "raw_exit_code": 0,
                "diagnostics": [],
            }
        ),
        encoding="utf-8",
    )

    result, valid = collect_build_diagnostics(
        diagnostics,
        returncode=None,
        timed_out=False,
        output_limited=True,
        stdout="x" * 8,
        stderr="",
        node_map={"document": "main.weave", "nodes": []},
        canonical_source_path=source,
        compiler_output_limit_bytes=8,
    )

    assert valid is False
    assert result["output_limited"] is True
    assert result["compiler_output_limit_bytes"] == 8
    assert result["entries"][0]["code"] == "bridge.compiler-output-limit"


def test_oversized_manifest_is_rejected_before_decode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import weave_frontend.compiler.manifest as module

    manifest = tmp_path / "compiler-manifest.json"
    manifest.write_bytes(b"x" * 17)
    monkeypatch.setattr(module, "MAX_COMPILER_PROTOCOL_BYTES", 16)

    document, errors = validate_compiler_manifest(
        manifest,
        expected_sources=[],
        expected_output=tmp_path / "program",
        requested_target=None,
        returncode=1,
        diagnostics_status="failed",
    )

    assert document is None
    assert len(errors) == 1
    assert "exceeds 16 bytes" in errors[0]


def test_compiler_bridge_wrapper_normalizes_output_termination(tmp_path: Path) -> None:
    script = _script(
        tmp_path,
        "import sys, time\n"
        "sys.stdout.buffer.write(b'x' * 64)\n"
        "sys.stdout.flush()\n"
        "time.sleep(10)\n",
        "build-compiler.py",
    )
    workspace = SimpleNamespace(db=SimpleNamespace(path=tmp_path / "weave.db"))
    bridge = CompilerBridge(
        workspace,
        compiler=script,
        build_root=tmp_path / "builds",
        timeout_seconds=2,
        max_output_bytes=32,
    )

    result = bridge._run_compiler([str(script)])

    assert result.returncode is None
    assert result.timed_out is False
    assert result.output_limited is True
    assert "exceeded the combined stdout/stderr limit of 32 bytes" in result.stderr
