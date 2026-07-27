"""Bubblewrap command construction compatible with older supported distributions."""

from __future__ import annotations

from pathlib import Path

from .sandbox import BubblewrapSandbox


class PortableBubblewrapSandbox(BubblewrapSandbox):
    """Run the strict sandbox without requiring Bubblewrap's newer ``--clearenv``.

    The sandboxed program is launched through ``env -i`` inside the namespace.
    This preserves the existing environment allowlist while remaining compatible
    with Bubblewrap 0.4.x as shipped by enterprise Linux distributions.
    """

    def _command(self, executable: Path, arguments: list[str]) -> list[str]:
        if self.executable is None:
            return []
        command = [
            str(self.executable),
            "--unshare-all",
            "--die-with-parent",
            "--new-session",
            "--cap-drop",
            "ALL",
        ]
        for path in self._runtime_paths():
            command.extend(["--ro-bind-try", path, path])
        command.extend(
            [
                "--proc",
                "/proc",
                "--dev",
                "/dev",
                "--tmpfs",
                "/tmp",
                "--tmpfs",
                "/work",
                "--dir",
                "/app",
                "--ro-bind",
                str(executable),
                "/app/program",
                "--chdir",
                "/work",
                "/usr/bin/env",
                "-i",
                "HOME=/nonexistent",
                "PATH=/usr/bin:/bin",
                "LANG=C",
                "LC_ALL=C",
                "TMPDIR=/tmp",
                "/app/program",
                *arguments,
            ]
        )
        return command
