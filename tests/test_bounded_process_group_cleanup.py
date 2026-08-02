from __future__ import annotations

import os
import select
import sys
from pathlib import Path

import pytest

from weave_frontend.bounded_process import run_bounded_process

pytestmark = pytest.mark.skipif(
    not hasattr(os, "mkfifo"),
    reason="requires POSIX FIFO support",
)


def _script(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "group-cleanup.py"
    path.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_timeout_prevents_grandchild_survival_after_leader_exit(
    tmp_path: Path,
) -> None:
    response_fifo = tmp_path / "survival-response"
    trigger = tmp_path / "check-survival"
    os.mkfifo(response_fifo)
    response_fd = os.open(response_fifo, os.O_RDONLY | os.O_NONBLOCK)

    grandchild = (
        "import os\n"
        "from pathlib import Path\n"
        f"response_fd = os.open({str(response_fifo)!r}, os.O_WRONLY)\n"
        f"trigger = Path({str(trigger)!r})\n"
        "print('ready', flush=True)\n"
        "while not trigger.exists():\n"
        "    pass\n"
        "os.write(response_fd, b'survived')\n"
    )
    script = _script(
        tmp_path,
        "import subprocess, sys\n"
        f"subprocess.Popen([sys.executable, '-c', {grandchild!r}])\n",
    )

    try:
        result = run_bounded_process(
            [script],
            timeout_seconds=0.5,
            max_output_bytes=128,
        )

        assert result.returncode == 0
        assert result.timed_out is True
        assert result.output_limited is False
        assert result.stdout == "ready\n"
        assert result.stderr == ""

        trigger.touch()
        readable, _, _ = select.select([response_fd], [], [], 1.0)
        assert readable == [response_fd]
        assert os.read(response_fd, 64) == b""
    finally:
        os.close(response_fd)
