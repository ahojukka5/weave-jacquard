from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
TRACE_CONTRACT = ROOT / "scripts" / "qualification-traces.json"


def _load_helper() -> ModuleType:
    path = ROOT / "scripts" / "qualification.py"
    spec = importlib.util.spec_from_file_location("jacquard_qualification", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


qualification = _load_helper()


def _executable(path: Path, body: str) -> Path:
    path.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_qualification_shell_scripts_parse() -> None:
    for path in (
        ROOT / "scripts" / "qualify.sh",
        ROOT / "scripts" / "qualify-immutable-revert.sh",
    ):
        completed = subprocess.run(
            ["bash", "-n", str(path)],
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr


def test_runner_never_deletes_requested_evidence_directory() -> None:
    source = (ROOT / "scripts" / "qualify.sh").read_text(encoding="utf-8")

    assert 'rm -rf "$out_dir"' not in source
    assert "output directory already exists" in (ROOT / "scripts" / "qualification.py").read_text(
        encoding="utf-8"
    )
    assert 'mv -T -n -- "$staging_dir" "$final_out"' in source


def test_release_version_fallback_is_explicit_and_audited() -> None:
    source = (ROOT / "scripts" / "qualify.sh").read_text(encoding="utf-8")

    assert "WEAVEC_RELEASE" in source
    assert "release-tag-fallback" in source
    assert "compiler-version-probe.txt" in source
    assert "weavec_version_source" in source


def test_resolve_output_requires_a_new_safe_directory(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    existing = root / "existing"
    existing.mkdir()

    resolved = qualification.resolve_output(root, "evidence/run")
    assert resolved == root / "evidence" / "run"

    with pytest.raises(qualification.QualificationError, match="already exists"):
        qualification.resolve_output(root, str(existing))
    with pytest.raises(qualification.QualificationError, match="unsafe"):
        qualification.resolve_output(root, str(root))
    with pytest.raises(qualification.QualificationError, match="unsafe"):
        qualification.resolve_output(root, "/")


def test_bounded_command_deadline_survives_closed_output(tmp_path: Path) -> None:
    executable = _executable(
        tmp_path / "closed-output.py",
        "import os, time\nos.close(1)\nos.close(2)\ntime.sleep(10)\n",
    )

    started = time.monotonic()
    returncode, output, timed_out, output_limited = qualification._run_bounded_command(
        [str(executable)],
        timeout_seconds=0.05,
        max_output_bytes=32,
    )

    assert returncode is None
    assert output == b""
    assert timed_out is True
    assert output_limited is False
    assert time.monotonic() - started < 2


def test_command_version_rejects_overflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    executable = _executable(
        tmp_path / "compiler.py",
        "import sys\nsys.stdout.write('x' * 17)\n",
    )
    monkeypatch.setattr(qualification, "MAX_VERSION_OUTPUT_BYTES", 16)

    with pytest.raises(qualification.QualificationError, match="exceeds 16 bytes"):
        qualification.command_version(executable)


def test_junit_summary_rejects_skips(tmp_path: Path) -> None:
    source = tmp_path / "junit.xml"
    source.write_text(
        '<testsuite tests="2" failures="0" errors="0" skipped="1"/>',
        encoding="utf-8",
    )

    with pytest.raises(qualification.QualificationError, match="rejects unexpected skips"):
        qualification.summarize_junit(source, tmp_path / "summary.json")


def test_trace_collection_is_bounded_and_hashes_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = tmp_path / "pytest"
    out = tmp_path / "evidence"
    base.mkdir()
    out.mkdir()
    contract = tmp_path / "contract.json"
    contract.write_text(
        json.dumps(
            {
                "format": qualification.TRACE_CONTRACT_FORMAT,
                "protocol": ["protocol-trace.json"],
                "native": ["native-trace.json"],
            }
        ),
        encoding="utf-8",
    )
    (base / "protocol-trace.json").write_text('{"ok":true}', encoding="utf-8")

    index = qualification.collect_traces(base, out, "python", contract)

    assert index["trace_count"] == 1
    assert index["required_basenames"] == ["protocol-trace.json"]
    assert len(index["contract_sha256"]) == 64
    assert (out / "qualification-traces.json").is_file()
    assert (out / "traces" / "protocol-trace.json").is_file()

    too_large = base / "extra-trace.json"
    too_large.write_bytes(b"x" * 1025)
    monkeypatch.setattr(qualification, "MAX_TRACE_BYTES", 1024)
    with pytest.raises(qualification.QualificationError, match="limit is 1024"):
        qualification.collect_traces(base, tmp_path / "rejected", "python", contract)


def test_trace_contract_is_unique_and_backed_by_e2e_tests() -> None:
    contract = json.loads(TRACE_CONTRACT.read_text(encoding="utf-8"))

    assert contract["format"] == qualification.TRACE_CONTRACT_FORMAT
    protocol = contract["protocol"]
    native = contract["native"]
    combined = [*protocol, *native]
    assert protocol
    assert native
    assert len(combined) == len(set(combined))
    assert all(name.endswith("-trace.json") for name in combined)

    e2e_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "tests" / "e2e").glob("test_*.py"))
    )
    missing = [name for name in combined if name not in e2e_source]
    assert missing == []
