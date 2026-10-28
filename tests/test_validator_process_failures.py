from __future__ import annotations

import shlex
import subprocess
import time
from pathlib import Path

import pytest

from weave_frontend.compiler import WeavecValidator

PROGRAM = '(program (name "demo") (version "0.1"))\n'


def test_validator_launch_failure_is_structured(tmp_path: Path) -> None:
    compiler = tmp_path / "weavec"
    compiler.write_text("#!/definitely/missing/interpreter\n", encoding="utf-8")
    compiler.chmod(0o755)

    result = WeavecValidator(compiler).validate(PROGRAM)

    assert result["available"] is False
    assert result["valid"] is None
    assert result["returncode"] is None
    assert result["timed_out"] is False
    assert result["documents"] == ["program.weave"]
    assert "could not start" in result["diagnostic"]
    assert "could not start" in result["stderr"]


def test_validator_timeout_preserves_partial_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiler = tmp_path / "weavec"
    ready = tmp_path / "output-ready"
    compiler.write_text(
        "#!/bin/sh\n"
        "printf 'partial stdout'\n"
        "printf 'partial stderr' >&2\n"
        f": > {shlex.quote(str(ready))}\n"
        "while :; do :; done\n",
        encoding="utf-8",
    )
    compiler.chmod(0o755)
    validator = WeavecValidator(compiler, timeout_seconds=0.05)

    popen = subprocess.Popen

    def start_after_output(*args, **kwargs):
        ready.unlink(missing_ok=True)
        process = popen(*args, **kwargs)
        deadline = time.monotonic() + 5
        while not ready.exists():
            if process.poll() is not None or time.monotonic() >= deadline:
                process.kill()
                process.wait()
                pytest.fail("compiler fixture did not emit its initial output")
            time.sleep(0.001)
        return process

    monkeypatch.setattr("weave_frontend.bounded_process.subprocess.Popen", start_after_output)

    for _ in range(25):
        result = validator.validate(PROGRAM)

        assert result["available"] is True
        assert result["valid"] is False
        assert result["returncode"] is None
        assert result["timed_out"] is True
        assert result["documents"] == ["program.weave"]
        assert "timed out" in result["diagnostic"]
        assert result["stdout"] == "partial stdout"
        assert result["stderr"] == "partial stderr"
