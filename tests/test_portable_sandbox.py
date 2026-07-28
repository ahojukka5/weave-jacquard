from __future__ import annotations

from pathlib import Path

from weave_frontend.sandbox import BubblewrapSandbox


def test_canonical_bubblewrap_uses_inner_environment_allowlist(tmp_path: Path) -> None:
    bwrap = tmp_path / "bwrap"
    bwrap.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    bwrap.chmod(0o755)
    prlimit = tmp_path / "prlimit"
    prlimit.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    prlimit.chmod(0o755)
    program = tmp_path / "program"
    program.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    program.chmod(0o755)

    command = BubblewrapSandbox(bwrap, prlimit=prlimit)._command(
        program,
        ["alpha", "beta"],
    )

    assert "--clearenv" not in command
    env_index = command.index("/usr/bin/env")
    assert command[env_index : env_index + 11] == [
        "/usr/bin/env",
        "-i",
        "HOME=/nonexistent",
        "PATH=/usr/bin:/bin",
        "LANG=C",
        "LC_ALL=C",
        "TMPDIR=/tmp",
        str(prlimit.resolve()),
        "--nproc=1:1",
        "--",
        "/app/program",
    ]
    assert command[-2:] == ["alpha", "beta"]
