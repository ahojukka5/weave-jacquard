"""Bounded subprocess execution for trusted compiler frontends."""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from collections.abc import Iterator, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

_READ_CHUNK = 65_536


@dataclass(frozen=True)
class BoundedProcessResult:
    """One completed, timed-out, or output-limited process invocation."""

    returncode: int | None
    timed_out: bool
    output_limited: bool
    stdout: str
    stderr: str

    def __iter__(self) -> Iterator[int | bool | str | None]:
        """Preserve the historical four-value compiler-result unpacking shape."""

        yield self.returncode
        yield self.timed_out
        yield self.stdout
        yield self.stderr


def run_bounded_process(
    command: Sequence[str | Path],
    *,
    timeout_seconds: float,
    max_output_bytes: int,
) -> BoundedProcessResult:
    """Run one command with a combined stdout/stderr byte ceiling.

    ``OSError`` from process launch is intentionally propagated so callers can retain
    their existing availability and launch-failure semantics.
    """

    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or timeout_seconds <= 0
    ):
        raise ValueError("timeout_seconds must be a positive number")
    if (
        isinstance(max_output_bytes, bool)
        or not isinstance(max_output_bytes, int)
        or max_output_bytes <= 0
    ):
        raise ValueError("max_output_bytes must be a positive integer")

    process = subprocess.Popen(
        [str(argument) for argument in command],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    stdout, stderr, timed_out, output_limited = _collect(
        process,
        timeout_seconds=float(timeout_seconds),
        max_output_bytes=max_output_bytes,
    )
    try:
        returncode = process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        _terminate_process_group(process)
        returncode = process.wait(timeout=1)
    finally:
        # A compiler parent can exit while descendants remain in its process group.
        # Remove those descendants before returning evidence to the caller.
        _terminate_process_group(process)
    return BoundedProcessResult(
        returncode=returncode,
        timed_out=timed_out,
        output_limited=output_limited,
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
    )


def _collect(
    process: subprocess.Popen[bytes],
    *,
    timeout_seconds: float,
    max_output_bytes: int,
) -> tuple[bytes, bytes, bool, bool]:
    assert process.stdout is not None
    assert process.stderr is not None
    selector = selectors.DefaultSelector()
    streams = {process.stdout: bytearray(), process.stderr: bytearray()}
    for stream in streams:
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ)

    deadline = time.monotonic() + timeout_seconds
    timed_out = False
    output_limited = False
    total = 0
    try:
        while selector.get_map() or process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                _terminate_process_group(process)
                break

            if not selector.get_map():
                with suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=min(remaining, 0.1))
                continue

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
                    _terminate_process_group(process)
                    break
                accepted = chunk[:capacity]
                streams[stream].extend(accepted)
                total += len(accepted)
                if len(accepted) < len(chunk):
                    output_limited = True
                    _terminate_process_group(process)
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


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    # The group may outlive its leader, so do not skip killpg merely because the
    # direct child has already exited and been reaped.
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    if process.poll() is None:
        with suppress(ProcessLookupError):
            process.kill()


__all__ = ["BoundedProcessResult", "run_bounded_process"]
