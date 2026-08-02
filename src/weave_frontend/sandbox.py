"""Strict process sandbox contract and a Linux bubblewrap implementation."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import resource
import selectors
import shutil
import signal
import subprocess
import tempfile
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .errors import ValidationError

SANDBOX_CAPABILITIES_FORMAT = "weave-sandbox-capabilities-v1"
SANDBOX_RESULT_FORMAT = "weave-sandbox-result-v1"
MAX_SANDBOX_VERSION_BYTES = 4096
_READ_CHUNK = 65_536
_SINGLE_PROCESS_LIMIT = 1
_FORK_DENIAL_MARKERS = (
    b"cannot fork",
    b"resource temporarily unavailable",
)


@dataclass(frozen=True)
class SandboxLimits:
    timeout_ms: int
    max_memory_bytes: int
    max_output_bytes: int
    max_file_bytes: int

    def __post_init__(self) -> None:
        for name in (
            "timeout_ms",
            "max_memory_bytes",
            "max_output_bytes",
            "max_file_bytes",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValidationError(
                    "INVALID_SANDBOX_LIMIT",
                    f"{name} must be a positive integer",
                )

    def as_dict(self) -> dict[str, int]:
        return {
            "timeout_ms": self.timeout_ms,
            "max_memory_bytes": self.max_memory_bytes,
            "max_output_bytes": self.max_output_bytes,
            "max_file_bytes": self.max_file_bytes,
            "max_processes": _SINGLE_PROCESS_LIMIT,
        }


@dataclass(frozen=True)
class SandboxResult:
    returncode: int | None
    signal: int | None
    termination_reason: str
    timed_out: bool
    output_limited: bool
    duration_ms: int
    stdout: bytes
    stderr: bytes

    def as_dict(self) -> dict[str, Any]:
        return {
            "format": SANDBOX_RESULT_FORMAT,
            "returncode": self.returncode,
            "signal": self.signal,
            "termination_reason": self.termination_reason,
            "timed_out": self.timed_out,
            "output_limited": self.output_limited,
            "duration_ms": self.duration_ms,
            "stdout_bytes": len(self.stdout),
            "stderr_bytes": len(self.stderr),
            "stdout_sha256": hashlib.sha256(self.stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(self.stderr).hexdigest(),
        }


class SandboxBackend(Protocol):
    def capabilities(self) -> dict[str, Any]: ...

    def run(
        self,
        executable: Path,
        arguments: list[str],
        stdin: bytes,
        limits: SandboxLimits,
    ) -> SandboxResult: ...


class BubblewrapSandbox:
    """Run one native executable in a default-deny bubblewrap namespace sandbox.

    The executable is mounted and invoked directly as ``/app/program``. Callers that
    need an interpreter must pass that interpreter binary as ``executable`` and provide
    the script or expression through ``arguments`` or ``stdin``.
    """

    def __init__(
        self,
        executable: str | Path | None = None,
        *,
        prlimit: str | Path | None = None,
    ) -> None:
        configured = executable or os.environ.get("WEAVE_BWRAP") or shutil.which("bwrap")
        configured_prlimit = prlimit or shutil.which("prlimit")
        self.executable = Path(configured).resolve() if configured else None
        self.prlimit = Path(configured_prlimit).resolve() if configured_prlimit else None
        self._capabilities: dict[str, Any] | None = None

    def capabilities(self) -> dict[str, Any]:
        if self._capabilities is not None:
            return dict(self._capabilities)

        error: str | None = None
        version: str | None = None
        available = False
        if platform.system() != "Linux":
            error = "bubblewrap execution is supported only on Linux"
        elif self.executable is None:
            error = "bubblewrap executable was not found"
        elif not self.executable.is_file() or not os.access(self.executable, os.X_OK):
            error = "configured bubblewrap path is not an executable file"
        elif self.prlimit is None:
            error = "prlimit executable was not found"
        elif not self.prlimit.is_file() or not os.access(self.prlimit, os.X_OK):
            error = "configured prlimit path is not an executable file"
        else:
            try:
                completed = subprocess.run(
                    [str(self.executable), "--version"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    check=False,
                    timeout=5,
                )
                raw_version = completed.stdout[:MAX_SANDBOX_VERSION_BYTES]
                version = raw_version.decode("utf-8", errors="replace").strip()
                if completed.returncode != 0:
                    error = f"bubblewrap version probe exited {completed.returncode}"
                else:
                    isolation_probe = subprocess.run(
                        self._command(Path("/usr/bin/true"), []),
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        check=False,
                        timeout=5,
                    )
                    if isolation_probe.returncode != 0:
                        message = isolation_probe.stdout[:MAX_SANDBOX_VERSION_BYTES].decode(
                            "utf-8", errors="replace"
                        ).strip()
                        error = (
                            f"bubblewrap isolation probe exited {isolation_probe.returncode}"
                            + (f": {message}" if message else "")
                        )
                    else:
                        process_probe = subprocess.run(
                            self._command(
                                Path("/bin/sh").resolve(),
                                ["-c", "( : ); exit 91"],
                            ),
                            stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            check=False,
                            timeout=5,
                        )
                        process_output = process_probe.stdout[
                            :MAX_SANDBOX_VERSION_BYTES
                        ]
                        if process_probe.returncode == 91:
                            error = "single-process policy allowed child process creation"
                        elif self._is_fork_denial(
                            process_probe.returncode,
                            process_output,
                        ):
                            available = True
                        else:
                            message = process_output.decode(
                                "utf-8", errors="replace"
                            ).strip()
                            error = (
                                "single-process policy probe exited "
                                f"{process_probe.returncode}"
                                + (f": {message}" if message else "")
                            )
            except (OSError, subprocess.TimeoutExpired) as exc:
                error = f"bubblewrap isolation probe failed: {exc}"

        policy = {
            "network": "deny",
            "filesystem": "isolated",
            "host_runtime_paths": self._runtime_paths(),
            "host_runtime_access": "read-only",
            "writable_paths": ["/tmp", "/work"],
            "writable_storage": "ephemeral-tmpfs",
            "capabilities": "drop-all",
            "process_creation": "deny",
            "max_processes": _SINGLE_PROCESS_LIMIT,
            "process_limit_backend": "prlimit-RLIMIT_NPROC",
            "new_user_namespace": True,
            "new_mount_namespace": True,
            "new_pid_namespace": True,
            "new_network_namespace": True,
            "new_ipc_namespace": True,
            "new_uts_namespace": True,
            "seccomp": False,
        }
        policy_hash = hashlib.sha256(
            json.dumps(policy, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        self._capabilities = {
            "format": SANDBOX_CAPABILITIES_FORMAT,
            "backend": "bubblewrap",
            "platform": platform.system().lower(),
            "available": available,
            "version": version,
            "probe_error": error,
            "policy": policy,
            "policy_hash": policy_hash,
            "resource_limits": {
                "wall_clock_timeout": True,
                "address_space": True,
                "cpu_time": True,
                "generated_file_size": True,
                "captured_output": True,
                "core_dump": True,
                "open_files": True,
                "process_count": True,
                "aggregate_memory": False,
            },
        }
        return dict(self._capabilities)

    def run(
        self,
        executable: Path,
        arguments: list[str],
        stdin: bytes,
        limits: SandboxLimits,
    ) -> SandboxResult:
        capabilities = self.capabilities()
        if not capabilities["available"]:
            raise ValidationError(
                "SANDBOX_UNAVAILABLE",
                str(capabilities["probe_error"] or "sandbox is unavailable"),
            )
        resolved = executable.resolve()
        if not resolved.is_file() or not os.access(resolved, os.X_OK):
            raise ValidationError(
                "INVALID_TEST_EXECUTABLE",
                "test executable must be an existing executable file",
            )
        if any("\x00" in argument for argument in arguments):
            raise ValidationError(
                "INVALID_TEST_ARGUMENT",
                "test arguments must not contain NUL bytes",
            )

        command = self._command(resolved, arguments)
        started = time.monotonic()
        with tempfile.TemporaryFile() as stdin_file:
            stdin_file.write(stdin)
            stdin_file.seek(0)
            process = subprocess.Popen(
                command,
                stdin=stdin_file,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={},
                start_new_session=True,
                preexec_fn=self._limit_process(limits),
            )
            stdout, stderr, timed_out, output_limited = self._collect(
                process,
                timeout_ms=limits.timeout_ms,
                max_output_bytes=limits.max_output_bytes,
            )
            returncode = process.wait()
        duration_ms = max(0, round((time.monotonic() - started) * 1000))
        signal_number = -returncode if returncode < 0 else None
        if timed_out:
            reason = "timeout"
        elif output_limited:
            reason = "output_limit"
        elif signal_number is not None:
            reason = "signal"
        else:
            reason = "exit"
        return SandboxResult(
            returncode=returncode if returncode >= 0 else None,
            signal=signal_number,
            termination_reason=reason,
            timed_out=timed_out,
            output_limited=output_limited,
            duration_ms=duration_ms,
            stdout=stdout,
            stderr=stderr,
        )

    def _command(self, executable: Path, arguments: list[str]) -> list[str]:
        if self.executable is None or self.prlimit is None:
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
                str(self.prlimit),
                f"--nproc={_SINGLE_PROCESS_LIMIT}:{_SINGLE_PROCESS_LIMIT}",
                "--",
                "/app/program",
                *arguments,
            ]
        )
        return command

    @staticmethod
    def _is_fork_denial(returncode: int, output: bytes) -> bool:
        if returncode == 0:
            return False
        normalized = output.lower()
        return any(marker in normalized for marker in _FORK_DENIAL_MARKERS)

    @staticmethod
    def _runtime_paths() -> list[str]:
        candidates = (
            "/usr",
            "/bin",
            "/lib",
            "/lib64",
            "/sbin",
            "/etc/ld.so.cache",
        )
        return [path for path in candidates if Path(path).exists()]

    @staticmethod
    def _limit_process(limits: SandboxLimits) -> Any:
        def apply() -> None:
            cpu_seconds = max(1, math.ceil(limits.timeout_ms / 1000) + 1)
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            resource.setrlimit(
                resource.RLIMIT_AS,
                (limits.max_memory_bytes, limits.max_memory_bytes),
            )
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
            resource.setrlimit(
                resource.RLIMIT_FSIZE,
                (limits.max_file_bytes, limits.max_file_bytes),
            )
            resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))

        return apply

    @classmethod
    def _collect(
        cls,
        process: subprocess.Popen[bytes],
        *,
        timeout_ms: int,
        max_output_bytes: int,
    ) -> tuple[bytes, bytes, bool, bool]:
        assert process.stdout is not None
        assert process.stderr is not None
        selector = selectors.DefaultSelector()
        streams = {process.stdout: bytearray(), process.stderr: bytearray()}
        for stream in streams:
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ)
        deadline = time.monotonic() + timeout_ms / 1000
        timed_out = False
        output_limited = False
        total = 0
        try:
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    cls._kill(process)
                    break
                events = selector.select(timeout=min(remaining, 0.1))
                if not events and process.poll() is not None:
                    events = [
                        (key, selectors.EVENT_READ)
                        for key in list(selector.get_map().values())
                    ]
                for key, _ in events:
                    stream = key.fileobj
                    try:
                        chunk = os.read(stream.fileno(), _READ_CHUNK)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(stream)
                        continue
                    capacity = max_output_bytes - total
                    if capacity <= 0:
                        output_limited = True
                        cls._kill(process)
                        break
                    accepted = chunk[:capacity]
                    streams[stream].extend(accepted)
                    total += len(accepted)
                    if len(accepted) < len(chunk):
                        output_limited = True
                        cls._kill(process)
                        break
                if timed_out or output_limited:
                    break
        finally:
            selector.close()
            for stream in streams:
                stream.close()
        return (
            bytes(streams[process.stdout]),
            bytes(streams[process.stderr]),
            timed_out,
            output_limited,
        )

    @staticmethod
    def _kill(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
