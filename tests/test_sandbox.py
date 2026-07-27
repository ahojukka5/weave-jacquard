from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from weave_frontend import ValidationError
from weave_frontend.sandbox import BubblewrapSandbox, SandboxLimits


def _limits(**overrides: int) -> SandboxLimits:
    values = {
        "timeout_ms": 2_000,
        "max_memory_bytes": 256 * 1024 * 1024,
        "max_output_bytes": 64 * 1024,
        "max_file_bytes": 1024 * 1024,
    }
    values.update(overrides)
    return SandboxLimits(**values)


def test_missing_bubblewrap_reports_unavailable_and_refuses_execution(
    tmp_path: Path,
) -> None:
    sandbox = BubblewrapSandbox(tmp_path / "missing-bwrap")
    capabilities = sandbox.capabilities()

    assert capabilities["format"] == "weave-sandbox-capabilities-v1"
    assert capabilities["backend"] == "bubblewrap"
    assert capabilities["available"] is False
    assert capabilities["policy"]["network"] == "deny"
    assert capabilities["policy"]["filesystem"] == "isolated"
    assert capabilities["policy"]["seccomp"] is False
    assert capabilities["policy_hash"]

    executable = tmp_path / "program"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    with pytest.raises(ValidationError) as raised:
        sandbox.run(executable, [], b"", _limits())
    assert raised.value.code == "SANDBOX_UNAVAILABLE"


def test_collector_allows_exact_limit_and_stops_excess_output() -> None:
    exact = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'x' * 16)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    stdout, stderr, timed_out, output_limited = BubblewrapSandbox._collect(
        exact,
        timeout_ms=2_000,
        max_output_bytes=16,
    )
    assert exact.wait() == 0
    assert stdout == b"x" * 16
    assert stderr == b""
    assert timed_out is False
    assert output_limited is False

    excessive = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'x' * 17)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    stdout, stderr, timed_out, output_limited = BubblewrapSandbox._collect(
        excessive,
        timeout_ms=2_000,
        max_output_bytes=16,
    )
    excessive.wait()
    assert stdout == b"x" * 16
    assert stderr == b""
    assert timed_out is False
    assert output_limited is True


def test_collector_enforces_wall_timeout() -> None:
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    stdout, stderr, timed_out, output_limited = BubblewrapSandbox._collect(
        process,
        timeout_ms=50,
        max_output_bytes=1024,
    )
    process.wait()
    assert stdout == b""
    assert stderr == b""
    assert timed_out is True
    assert output_limited is False


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap not installed")
def test_bubblewrap_denies_host_files_and_host_network(tmp_path: Path) -> None:
    sandbox = BubblewrapSandbox()
    capabilities = sandbox.capabilities()
    if not capabilities["available"]:
        pytest.skip(str(capabilities["probe_error"]))

    secret = tmp_path / "host-secret"
    secret.write_text("must-not-be-visible", encoding="utf-8")
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    program = tmp_path / "sandbox-check.py"
    program.write_text(
        """#!/usr/bin/python3
import pathlib
import socket
import sys

secret = pathlib.Path(sys.argv[1])
if secret.exists():
    raise SystemExit(80)
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(0.25)
try:
    sock.connect(("127.0.0.1", int(sys.argv[2])))
except OSError:
    print("isolated")
    raise SystemExit(0)
raise SystemExit(81)
""",
        encoding="utf-8",
    )
    program.chmod(0o755)
    try:
        result = sandbox.run(
            program,
            [str(secret), str(port)],
            b"",
            _limits(),
        )
    finally:
        server.close()

    assert result.returncode == 0
    assert result.termination_reason == "exit"
    assert result.stdout == b"isolated\n"
    assert result.stderr == b""
    assert result.timed_out is False
    assert result.output_limited is False
    assert os.path.exists(secret)
