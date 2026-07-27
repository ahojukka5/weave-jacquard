from __future__ import annotations

from pathlib import Path

from weave_frontend.portable_sandbox import PortableBubblewrapSandbox


def test_portable_bubblewrap_uses_inner_environment_allowlist(tmp_path: Path) -> None:
    bwrap = tmp_path / "bwrap"
    bwrap.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    bwrap.chmod(0o755)
    program = tmp_path / "program"
    program.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    program.chmod(0o755)

    command = PortableBubblewrapSandbox(bwrap)._command(program, ["alpha", "beta"])

    assert "--clearenv" not in command
    env_index = command.index("/usr/bin/env")
    assert command[env_index : env_index + 8] == [
        "/usr/bin/env",
        "-i",
        "HOME=/nonexistent",
        "PATH=/usr/bin:/bin",
        "LANG=C",
        "LC_ALL=C",
        "TMPDIR=/tmp",
        "/app/program",
    ]
    assert command[-2:] == ["alpha", "beta"]
